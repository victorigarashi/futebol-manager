"""Atomic optional JSON snapshots for the explicitly in-memory application."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 2


def _canonical_rooms(payload: dict[str, object]) -> bytes:
    rooms = payload.get("rooms")
    if not isinstance(rooms, dict):
        raise ValueError("Snapshot inválido: campo rooms ausente ou inválido.")
    return json.dumps(rooms, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_snapshot(path: Path) -> dict[str, object]:
    """Load current and legacy snapshots without ever replacing a corrupt file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rooms"), dict):
        raise ValueError("Snapshot inválido: formato de salas incompatível.")
    version = payload.get("schema_version", 1)
    if not isinstance(version, int) or version not in {1, SCHEMA_VERSION}:
        raise ValueError(f"Versão de snapshot não suportada: {version}.")
    checksum = payload.get("checksum_sha256")
    if version >= 2 and not isinstance(checksum, str):
        raise ValueError("Snapshot inválido: checksum ausente.")
    if checksum is not None and checksum != hashlib.sha256(_canonical_rooms(payload)).hexdigest():
        raise ValueError("Snapshot corrompido: checksum não confere.")
    payload.setdefault("schema_version", version)
    return payload


def write_snapshot(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    versioned = dict(payload)
    versioned["schema_version"] = SCHEMA_VERSION
    versioned["checksum_sha256"] = hashlib.sha256(_canonical_rooms(versioned)).hexdigest()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(versioned, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
