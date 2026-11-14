import asyncio
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect


class RoomConnectionHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[room_id].add(websocket)

    async def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        self._connections[room_id].discard(websocket)
        if not self._connections[room_id]:
            self._connections.pop(room_id, None)

    async def broadcast(self, room_id: str, event: dict[str, object]) -> None:
        async def deliver(websocket: WebSocket) -> None:
            try:
                await asyncio.wait_for(websocket.send_json(event), timeout=.5)
            except (RuntimeError, OSError, WebSocketDisconnect, TimeoutError):
                await self.disconnect(room_id, websocket)
        await asyncio.gather(*(deliver(ws) for ws in self._connections.get(room_id, set()).copy()))


hub = RoomConnectionHub()
