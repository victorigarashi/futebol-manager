"""Room WebSockets with one writer per connection and explicit backpressure.

Two kinds of traffic share a socket:

* **reliable** messages (room/season notifications, `live.state` with match events
  and sequence numbers, `live.stats`): kept in order in a bounded queue. If a client
  falls so far behind that the queue overflows, the queue is replaced by a single
  `live.resync` message: the client then reconciles over HTTP (the authoritative
  source). A reliable message is never silently dropped.
* **visual** messages (`live.frames`, 2D positions): disposable. While one is waiting
  to be written, newer frames are merged into it (rows de-duplicated, capped), so a
  slow client gets fewer, larger updates instead of an unbounded backlog. Broadcast
  timeline segments inside them are always kept (merged), they pace the playback.

Every write goes through the connection's single writer task, so two coroutines can
never send on the same socket concurrently. A client whose socket does not accept a
write within SEND_TIMEOUT seconds is considered permanently slow: it is closed with
code 1013 ("try again later"), reconnects with backoff and reconciles over HTTP.
An in-memory queue is not delivery after a disconnect: on reconnect the client
always re-reads the state (`season.sync` + HTTP).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import WebSocket

HEARTBEAT_SECONDS = 1.0
MAX_RELIABLE_QUEUE = 128
MAX_COALESCED_ROWS = 240
SEND_TIMEOUT = 2.0
STATS = {"bytes_sent": 0, "messages_sent": 0, "frames_coalesced": 0, "rows_dropped": 0, "resyncs": 0, "slow_closes": 0}
BYTES_BY_TYPE: dict[str, int] = defaultdict(int)
MESSAGES_BY_TYPE: dict[str, int] = defaultdict(int)
LARGEST_PAYLOAD: dict[str, int] = defaultdict(int)


def _merge_segments(old: list[dict[str, object]] | None, new: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
    if not old:
        return new
    if not new:
        return old
    merged = {float(s["r0"]): s for s in old}
    merged.update({float(s["r0"]): s for s in new})
    return [merged[key] for key in sorted(merged)]


class Channel:
    """One WebSocket: its metadata, its queues and its single writer task."""

    def __init__(self, room_id: str, websocket: WebSocket, club: str | None, on_dead: Callable[[Channel], None]) -> None:
        self.room_id = room_id
        self.websocket = websocket
        self.club = club
        self.meta: dict[str, object] = {"club": club, "tick": -1, "match_id": None, "timeline": None, "sent_at": 0.0,
                                        "live": None, "stats_at": 0.0, "state_at": 0.0}
        self.reliable: deque[str] = deque()
        self.visual: dict[str, object] | None = None
        self.closed = False
        self._wake = asyncio.Event()
        self._on_dead = on_dead
        self.task = asyncio.create_task(self._writer())

    # ------------------------------------------------------------------ enqueue
    def send_reliable(self, message: dict[str, object] | str) -> None:
        if self.closed:
            return
        text = message if isinstance(message, str) else json.dumps(message, separators=(",", ":"))
        if len(self.reliable) >= MAX_RELIABLE_QUEUE:
            # Too far behind to catch up message by message: ask for a full reconciliation.
            self.reliable.clear()
            self.meta["live"] = None
            STATS["resyncs"] += 1
            text = json.dumps({"type": "live.resync", "reason": "backlog"})
        self.reliable.append(text)
        self._wake.set()

    def send_visual(self, message: dict[str, object]) -> None:
        if self.closed:
            return
        pending = self.visual
        if pending is not None and pending.get("match_id") == message.get("match_id"):
            STATS["frames_coalesced"] += 1
            rows = {int(row["t"]): row for row in (pending.get("frames") or [])}
            rows.update({int(row["t"]): row for row in (message.get("frames") or [])})
            ordered = [rows[t] for t in sorted(rows)]
            if len(ordered) > MAX_COALESCED_ROWS:
                STATS["rows_dropped"] += len(ordered) - MAX_COALESCED_ROWS
                ordered = ordered[-MAX_COALESCED_ROWS:]
            merged = {**message, "frames": ordered}
            segments = _merge_segments(pending.get("broadcast"), message.get("broadcast"))  # type: ignore[arg-type]
            if segments is not None:
                merged["broadcast"] = segments
            self.visual = merged
        else:
            self.visual = message
        self._wake.set()

    @property
    def backlog(self) -> int:
        return len(self.reliable) + (1 if self.visual is not None else 0)

    # ------------------------------------------------------------------ writer
    async def _writer(self) -> None:
        try:
            while not self.closed:
                await self._wake.wait()
                self._wake.clear()
                while not self.closed and (self.reliable or self.visual is not None):
                    if self.reliable:
                        text = self.reliable.popleft()
                    else:
                        message, self.visual = self.visual, None
                        text = json.dumps(message, separators=(",", ":"))
                    await self._write(text)
        finally:
            self.closed = True
            self._on_dead(self)

    async def _write(self, text: str) -> None:
        try:
            await asyncio.wait_for(self.websocket.send_text(text), timeout=SEND_TIMEOUT)
        except TimeoutError:
            # Permanently slow consumer: free the server, the client reconnects and resyncs.
            STATS["slow_closes"] += 1
            self.closed = True
            try:
                await asyncio.wait_for(self.websocket.close(code=1013), timeout=0.5)
            except Exception:  # noqa: BLE001 - the socket is already unusable
                pass
            return
        except Exception:  # noqa: BLE001 - disconnects surface as several exception types
            self.closed = True
            return
        kind = text[9:text.find('"', 9)] if text.startswith('{"type":"') else "text"
        size = len(text)
        STATS["bytes_sent"] += size
        STATS["messages_sent"] += 1
        BYTES_BY_TYPE[kind] += size
        MESSAGES_BY_TYPE[kind] += 1
        LARGEST_PAYLOAD[kind] = max(LARGEST_PAYLOAD[kind], size)

    def close(self) -> None:
        self.closed = True
        self._wake.set()


class RoomConnectionHub:
    def __init__(self) -> None:
        self._channels: dict[str, dict[WebSocket, Channel]] = defaultdict(dict)

    # ------------------------------------------------------------------ connections
    async def connect(self, room_id: str, websocket: WebSocket, club: str | None = None) -> Channel:
        await websocket.accept()
        channel = Channel(room_id, websocket, club, self._forget)
        self._channels[room_id][websocket] = channel
        return channel

    def _forget(self, channel: Channel) -> None:
        room = self._channels.get(channel.room_id)
        if room is not None:
            room.pop(channel.websocket, None)
            if not room:
                self._channels.pop(channel.room_id, None)

    async def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        channel = self._channels.get(room_id, {}).get(websocket)
        if channel is not None:
            channel.close()
            self._forget(channel)

    def channel(self, room_id: str, websocket: WebSocket) -> Channel | None:
        return self._channels.get(room_id, {}).get(websocket)

    def channels(self, room_id: str) -> list[Channel]:
        return [channel for channel in self._channels.get(room_id, {}).values() if not channel.closed]

    def connections_by_room(self) -> dict[str, int]:
        return {room_id: len(channels) for room_id, channels in self._channels.items()}

    # ------------------------------------------------------------------ sending
    async def broadcast(self, room_id: str, event: dict[str, object]) -> None:
        text = json.dumps(event, separators=(",", ":"))
        for channel in self.channels(room_id):
            channel.send_reliable(text)

    async def push_frames(self, room_id: str, frames_for: Callable[[str, int, object], dict[str, object]]) -> None:
        """Incremental 2D frames: each coach receives only his own match.

        The broadcast timeline (which ticks play when) rides along only when it changed."""
        now = time.monotonic()
        for channel in self.channels(room_id):
            meta = channel.meta
            if not meta["club"]:
                continue
            known = meta["timeline"] if meta["match_id"] else None
            view = frames_for(str(meta["club"]), int(meta["tick"]) if meta["match_id"] else -1, known)
            if view.get("match_id") != meta["match_id"]:
                meta.update(match_id=view.get("match_id"), tick=-1, timeline=None)
                view = frames_for(str(meta["club"]), -1, None)
            rows = view.get("frames") or []
            timeline = view.get("timeline")
            # Nothing new: stay silent, except for a heartbeat every second so the
            # client's server-clock estimate stays fresh through breaks and cuts.
            if not rows and timeline == meta.get("timeline") and now - float(meta.get("sent_at") or 0) < HEARTBEAT_SECONDS:
                continue
            message: dict[str, object] = {"type": "live.frames", "match_id": view.get("match_id"), "frames": rows,
                                          "server_now": view.get("server_now"), "tick": view.get("tick")}
            if "broadcast" in view and timeline != meta.get("timeline"):
                message["broadcast"] = view["broadcast"]
            channel.send_visual(message)
            if rows:
                meta["tick"] = rows[-1]["t"]
            meta["timeline"] = timeline
            meta["sent_at"] = now

    async def push_live_state(self, room_id: str, state_for: Callable[[str, dict | None, bool], dict | None],
                              stats_for: Callable[[str], dict | None], stats_every: float = 5.0) -> None:
        """Reliable incremental match state (events with sequence numbers, scores, table)
        and the compact side-panel statistics every few seconds."""
        now = time.monotonic()
        for channel in self.channels(room_id):
            meta = channel.meta
            if not meta["club"]:
                continue
            heartbeat = now - float(meta.get("state_at") or 0) >= stats_every
            message = state_for(str(meta["club"]), meta.get("live"), heartbeat)  # type: ignore[arg-type]
            if message is not None:
                meta["live"] = message.pop("_known")
                meta["state_at"] = now
                channel.send_reliable(message)
            if now - float(meta.get("stats_at") or 0) >= stats_every:
                stats = stats_for(str(meta["club"]))
                meta["stats_at"] = now
                if stats is not None:
                    channel.send_reliable(stats)


def snapshot() -> dict[str, object]:
    return {**STATS, "bytes_by_type": dict(BYTES_BY_TYPE), "messages_by_type": dict(MESSAGES_BY_TYPE),
            "largest_payload_bytes": dict(LARGEST_PAYLOAD),
            # Counts only: room identifiers never leave the server through metrics.
            "connections_per_room": sorted(hub.connections_by_room().values(), reverse=True)}


hub = RoomConnectionHub()
