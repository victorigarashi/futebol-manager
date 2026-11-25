"""Static, read-only inventory of a PES 2013 Web runtime directory supplied by the user.

Nothing is executed, imported, uploaded or copied into the repository: the files are read as
bytes and searched. Use it on the runtime the user legitimately owns, from outside that
directory (the runtime's files are untrusted data):

    cd backend && ../.venv/bin/python -I tools/pes_runtime_inventory.py /path/to/runtime > report.json

The report answers, with evidence (file, offset, short excerpt), the Phase 2 questions:
- how the worker is created and which messages it receives (input / keydown / keyup ...);
- which files the runtime mounts or fetches (manifest.json, data packs, .bin, .wasm);
- whether anything mentions EDIT / option files / saves, and where saves are persisted
  (IndexedDB, localStorage, OPFS);
- the network bridge (netRelay / wsaRelayUrl / host_net_* / Winsock / WebSocket);
- the kind of each binary by its magic bytes (PE32 'MZ', WebAssembly, zip, ...).

It does NOT decide anything: an occurrence of "EDIT.bin" proves the string exists, not that the
runtime reads that file or in which format. That needs the runtime experiments.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

MAX_TEXT_BYTES = 40 * 1024 * 1024       # text files larger than this are only hashed
MAX_BINARY_SCAN = 64 * 1024 * 1024      # binaries: scan this much for ASCII/UTF-16 strings
EXCERPT = 80
MAX_HITS = 12

PROBES: dict[str, list[str]] = {
    "worker_creation": [r"new\s+Worker\s*\(", r"worker-[A-Za-z0-9_-]+\.js"],
    "messages": [r"postMessage\s*\(", r"\bonmessage\b", r"addEventListener\(\s*['\"]message['\"]"],
    "keyboard": [r"\bkeydown\b", r"\bkeyup\b", r"['\"]input['\"]", r"dinput_key", r"xinput_pad", r"user32_window_input"],
    "filesystem": [r"manifest\.json", r"\bFS\.\w+", r"\bmount\b", r"\.wasm\b", r"\.bin\b", r"\.cpk\b", r"\.img\b"],
    "roster_and_saves": [r"EDIT\w*\.bin", r"\bEDIT\d*\b", r"[Oo]ption\s?[Ff]ile", r"\bKONAMI-WIN32", r"\bsave\b", r"\bSaveData\b"],
    "persistence": [r"indexedDB", r"localStorage", r"navigator\.storage", r"getDirectory\s*\(", r"\bOPFS\b"],
    "network": [r"netRelay", r"wsaRelayUrl", r"host_net_\w+", r"winsock\w*", r"WebSocket\s*\(", r"\bws://", r"127\.0\.0\.1", r"localhost"],
    "match_flow": [r"[Ee]xhibition", r"[Kk]ick[- ]?[Oo]ff", r"[Ff]ull[- ]?[Tt]ime", r"\bscore\b", r"\bresult\b"],
}
TEXT_SUFFIXES = {".js", ".mjs", ".json", ".html", ".htm", ".txt", ".md", ".css", ".map", ".ini", ".cfg", ".xml"}
MAGIC = [(b"MZ", "PE/DOS executable (MZ)"), (b"\x00asm", "WebAssembly module"), (b"PK\x03\x04", "zip archive"),
         (b"\x1f\x8b", "gzip"), (b"CPK ", "CRI CPK archive"), (b"{", "JSON/text"), (b"<", "HTML/XML")]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def magic(head: bytes) -> str:
    return next((label for sig, label in MAGIC if head.startswith(sig)), "unknown")


def probe_text(text: str) -> dict[str, list[dict[str, object]]]:
    found: dict[str, list[dict[str, object]]] = {}
    for group, patterns in PROBES.items():
        hits = []
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                start = max(0, m.start() - EXCERPT // 2)
                hits.append({"pattern": pattern, "offset": m.start(),
                             "excerpt": text[start:m.end() + EXCERPT // 2].replace("\n", " ")[: EXCERPT * 2]})
                if len(hits) >= MAX_HITS:
                    break
        if hits:
            found[group] = hits
    return found


def binary_strings(data: bytes) -> str:
    """Printable ASCII and UTF-16LE runs (>= 5 chars), joined: enough for the probes."""
    ascii_runs = re.findall(rb"[\x20-\x7e]{5,}", data)
    utf16_runs = re.findall(rb"(?:[\x20-\x7e]\x00){5,}", data)
    return "\n".join([r.decode("ascii") for r in ascii_runs] + [r.decode("utf-16le") for r in utf16_runs])


def inventory(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")
    files, probes, manifest = [], {}, None
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = str(path.relative_to(root))
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(16)
        files.append({"path": rel, "bytes": size, "sha256": sha256(path), "kind": magic(head)})
        if path.suffix.lower() in TEXT_SUFFIXES and size <= MAX_TEXT_BYTES:
            text = path.read_bytes().decode("utf-8", errors="replace")
            if path.name == "manifest.json":
                try:
                    data = json.loads(text)
                    manifest = {"path": rel, "top_level_keys": sorted(data) if isinstance(data, dict) else None,
                                "entries": len(data) if isinstance(data, (list, dict)) else None}
                except json.JSONDecodeError as error:
                    manifest = {"path": rel, "error": str(error)}
        elif path.suffix.lower() not in TEXT_SUFFIXES:
            with path.open("rb") as f:
                text = binary_strings(f.read(MAX_BINARY_SCAN))
        else:
            continue
        found = probe_text(text)
        if found:
            probes[rel] = found
    summary = {group: sorted(f for f, groups in probes.items() if group in groups) for group in PROBES}
    return {"root": root.name, "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files), "manifest": manifest,
            "files": files, "evidence_by_question": summary, "probes": probes,
            "note": "Static strings only: an occurrence proves a string exists, not that the runtime uses it."}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: pes_runtime_inventory.py <runtime-directory>")
    print(json.dumps(inventory(Path(sys.argv[1])), ensure_ascii=False, indent=1))
