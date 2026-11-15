import asyncio
from collections import defaultdict
from collections.abc import Callable

from fastapi import WebSocket, WebSocketDisconnect


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

    async def push_frames(self, room_id: str, frames_for: Callable[[str, int], dict[str, object]]) -> None:
        """Incremental 2D frames over the socket: each coach receives only his own match.

        The broadcast timeline (which ticks play when) rides along whenever a new
        segment has started, so the client can pace playback on the server's clock."""
        async def deliver(websocket: WebSocket) -> None:
            meta = self._meta.get(websocket)
            if not meta or not meta["club"]:
                return
            view = frames_for(str(meta["club"]), int(meta["tick"]) if meta["match_id"] else -1)
            rows = view.get("frames") or []
            if view.get("match_id") != meta["match_id"]:
                meta.update(match_id=view.get("match_id"), tick=-1, timeline=None)
            segments = view.get("broadcast") or []
            timeline = (len(segments), segments[-1]["r0"]) if segments else None
            if not rows and timeline == meta.get("timeline"):
                return
            message: dict[str, object] = {"type": "live.frames", "match_id": view.get("match_id"), "frames": rows,
                                          "server_now": view.get("server_now"), "tick": view.get("tick")}
            if timeline != meta.get("timeline"):
                message["broadcast"] = segments
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=.5)
                if rows:
                    meta["tick"] = rows[-1]["t"]
                meta["timeline"] = timeline
            except (RuntimeError, OSError, WebSocketDisconnect, TimeoutError):
                await self.disconnect(room_id, websocket)
        await asyncio.gather(*(deliver(ws) for ws in self._connections.get(room_id, set()).copy()))


hub = RoomConnectionHub()
