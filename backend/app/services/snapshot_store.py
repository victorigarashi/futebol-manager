"""Incremental, non-blocking JSON snapshots.

The previous implementation re-read and re-parsed the whole snapshot file and then
re-serialised every room (pretty-printed) on every single action. A season of
finished matches weighs ~25 MB per room, so on a 0.1 CPU host each click could
freeze the event loop for seconds.

Here every room is kept serialised in memory in the canonical form used by the
checksum (sorted keys, compact separators). Finished matches never change again,
so their JSON is computed once and reused. Writing the file (hash + disk I/O, both
GIL-free) happens in a worker thread, debounced, never on the request path.
The file format is the one ``load_snapshot`` already reads (schema 2, checksum
over the canonical rooms map).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from app.services.snapshots import SCHEMA_VERSION, load_snapshot

logger = logging.getLogger(__name__)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SnapshotStore:
    def __init__(self, debounce_seconds: float = 1.0) -> None:
        self.debounce_seconds = debounce_seconds
        self._rooms: dict[str, str] = {}
        self._match_cache: dict[str, tuple[object, str]] = {}
        self._loaded_from: Path | None = None
        self._dirty = False
        self._flush_task: asyncio.Task | None = None
        self._write_lock = threading.Lock()
        self.writes = 0

    # ------------------------------------------------------------------ serialisation
    def _match_json(self, match_id: str, match: object) -> str:
        cached = self._match_cache.get(match_id)
        if cached is not None and cached[0] is match:
            return cached[1]
        text = canonical(match)
        # Only finished records are immutable (live matches are rebuilt on every export).
        if isinstance(match, dict) and match.get("status") == "FINISHED":
            self._match_cache[match_id] = (match, text)
        return text

    def _season_json(self, season: dict[str, object]) -> str:
        parts = []
        for key in sorted(season):
            value = season[key]
            if key == "matches" and isinstance(value, dict):
                body = ",".join(f"{canonical(str(mid))}:{self._match_json(str(mid), value[mid])}" for mid in sorted(value))
                parts.append(f"{canonical(key)}:{{{body}}}")
            else:
                parts.append(f"{canonical(key)}:{canonical(value)}")
        return "{" + ",".join(parts) + "}"

    def room_json(self, payload: dict[str, object]) -> str:
        parts = []
        for key in sorted(payload):
            value = payload[key]
            text = self._season_json(value) if key == "season" and isinstance(value, dict) else canonical(value)
            parts.append(f"{canonical(key)}:{text}")
        return "{" + ",".join(parts) + "}"

    # ------------------------------------------------------------------ state
    def _ensure_loaded(self, path: Path) -> None:
        """Rooms written by a previous process stay in the file (read once, not per action)."""
        if self._loaded_from == path:
            return
        self._loaded_from = path
        if not path.exists():
            return
        try:
            stored = load_snapshot(path)
        except (OSError, ValueError) as error:
            logger.warning("Snapshot existente ignorado para escrita incremental: %s", error)
            return
        for room_id, raw in stored.get("rooms", {}).items():
            self._rooms.setdefault(str(room_id), canonical(raw))

    def update(self, path: Path, room_id: str, payload: dict[str, object]) -> None:
        self._ensure_loaded(path)
        self._rooms[room_id] = self.room_json(payload)
        self._dirty = True

    def document(self) -> str:
        rooms = "{" + ",".join(f"{canonical(rid)}:{self._rooms[rid]}" for rid in sorted(self._rooms)) + "}"
        checksum = hashlib.sha256(rooms.encode("utf-8")).hexdigest()
        return f'{{"checksum_sha256":{canonical(checksum)},"rooms":{rooms},"schema_version":{SCHEMA_VERSION}}}\n'

    # ------------------------------------------------------------------ writing
    def write_now(self, path: Path) -> None:
        document = self.document()
        self._dirty = False
        self._write_document(path, document)

    def schedule(self, path: Path) -> None:
        """Debounced background write; synchronous when no event loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.write_now(path)
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = loop.create_task(self._flush_later(path))

    async def _flush_later(self, path: Path) -> None:
        await asyncio.sleep(self.debounce_seconds)
        if not self._dirty:
            return
        document = self.document()  # assembled on the loop (cheap string joins), written off it
        self._dirty = False
        try:
            await asyncio.to_thread(self._write_document, path, document)
        except OSError as error:
            self._dirty = True
            logger.error("Falha ao gravar snapshot: %s", error)

    def _write_document(self, path: Path, document: str) -> None:
        with self._write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                    handle.write(document)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary = Path(handle.name)
                os.replace(temporary, path)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            self.writes += 1

    async def flush(self, path: Path) -> None:
        """Final write on shutdown (or when a caller needs the file now)."""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        if self._dirty:
            document = self.document()
            self._dirty = False
            await asyncio.to_thread(self._write_document, path, document)


snapshot_store = SnapshotStore()
