"""The Phase 2 inventory tool on SYNTHETIC files (no PES file is used or needed here).

The fixture imitates only the shapes the tool must recognise (a worker script, a manifest, a
binary with an MZ header and UTF-16 strings); it says nothing about the real runtime.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location("pes_runtime_inventory", Path(__file__).parents[2] / "tools" / "pes_runtime_inventory.py")
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)


def test_inventory_reports_evidence_without_executing_anything(tmp_path):
    (tmp_path / "index.html").write_text("<script>const w = new Worker('worker-ABC123.js'); w.postMessage({type:'input', ev:'keydown'})</script>")
    (tmp_path / "worker-ABC123.js").write_text("self.onmessage = e => {}; const u = netRelay || 'ws://127.0.0.1:9000/'; host_net_open(); indexedDB.open('x')")
    (tmp_path / "manifest.json").write_text(json.dumps({"files": ["data/a.bin"], "version": "t"}))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "game.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64 + "save\\EDIT00000000".encode("utf-16le") + b"\x00" * 8)
    report = inv.inventory(tmp_path)
    assert report["file_count"] == 4
    kinds = {f["path"]: f["kind"] for f in report["files"]}
    assert kinds["data/game.exe"].startswith("PE") and kinds["manifest.json"] == "JSON/text"
    assert report["manifest"]["top_level_keys"] == ["files", "version"]
    ev = report["evidence_by_question"]
    assert "index.html" in ev["worker_creation"] and "index.html" in ev["keyboard"]
    assert "worker-ABC123.js" in ev["network"] and "worker-ABC123.js" in ev["persistence"]
    assert "data/game.exe" in ev["roster_and_saves"]            # found in a UTF-16 string of the binary
    assert all(len(f["sha256"]) == 64 for f in report["files"])


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("netRelay")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "link.js").symlink_to(outside)
    assert inv.inventory(runtime)["file_count"] == 0
