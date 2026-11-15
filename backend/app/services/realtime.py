import asyncio
import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect

HEARTBEAT_SECONDS = 1.0


class RoomConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # Per-socket club and frame cursor, used to stream each coach his own match.
        self._meta: dict[WebSocket, dict[str, object]] = {}

    async def connect(self, room_id: str, websocket: WebSocket, club: str | None = None) -> None:
        await websocket.accept()
        self._connections[room_id].add(websocket)
        self._meta[websocket] = {"club": club, "tick": -1, "match_id": None, "timeline": None}

    async def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        self._connections[room_id].discard(websocket)
        self._meta.pop(websocket, None)
        if not self._connections[room_id]:
            self._connections.pop(room_id, None)

    async def broadcast(self, room_id: str, event: dict[str, object]) -> None:
        async def deliver(websocket: WebSocket) -> None:
            try:
                await asyncio.wait_for(websocket.send_json(event), timeout=.5)
            except (RuntimeError, OSError, WebSocketDisconnect, TimeoutError):
                await self.disconnect(room_id, websocket)
        await asyncio.gather(*(deliver(ws) for ws in self._connections.get(room_id, set()).copy()))

    async def push_frames(self, room_id: str, frames_for: Callable[[str, int, object], dict[str, object]]) -> None:
        """Incremental 2D frames over the socket: each coach receives only his own match.

        The broadcast timeline (which ticks play when) rides along only when it changed,
        so the client can pace playback on the server's clock."""
        async def deliver(websocket: WebSocket) -> None:
            meta = self._meta.get(websocket)
            if not meta or not meta["club"]:
                return
            known = meta["timeline"] if meta["match_id"] else None
            view = frames_for(str(meta["club"]), int(meta["tick"]) if meta["match_id"] else -1, known)
            if view.get("match_id") != meta["match_id"]:
                meta.update(match_id=view.get("match_id"), tick=-1, timeline=None)
                view = frames_for(str(meta["club"]), -1, None)
            rows = view.get("frames") or []
            timeline = view.get("timeline")
            now = time.monotonic()
            # Nothing new: stay silent, except for a heartbeat every second so the
            # client's server-clock estimate stays fresh through breaks and cuts.
            if not rows and timeline == meta.get("timeline") and now - float(meta.get("sent_at") or 0) < HEARTBEAT_SECONDS:
                return
            message: dict[str, object] = {"type": "live.frames", "match_id": view.get("match_id"), "frames": rows,
                                          "server_now": view.get("server_now"), "tick": view.get("tick")}
            if "broadcast" in view and timeline != meta.get("timeline"):
                message["broadcast"] = view["broadcast"]
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=.5)
                if rows:
                    meta["tick"] = rows[-1]["t"]
                meta["timeline"] = timeline
                meta["sent_at"] = now
            except (RuntimeError, OSError, WebSocketDisconnect, TimeoutError):
                await self.disconnect(room_id, websocket)
        await asyncio.gather(*(deliver(ws) for ws in self._connections.get(room_id, set()).copy()))


hub = RoomConnectionHub()
