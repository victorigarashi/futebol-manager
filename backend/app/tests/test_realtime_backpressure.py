"""WebSocket backpressure and the sequenced live state."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.services import realtime
from app.services.realtime import MAX_COALESCED_ROWS, MAX_RELIABLE_QUEUE, RoomConnectionHub
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog


class FakeSocket:
    """Records writes; can be made slow or stuck, and detects concurrent sends."""

    def __init__(self, delay: float = 0.0, stuck: bool = False) -> None:
        self.sent: list[str] = []
        self.delay = delay
        self.stuck = stuck
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed_with: int | None = None

    async def accept(self) -> None:
        return None

    async def send_text(self, text: str) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.stuck:
                await asyncio.sleep(3600)
            await asyncio.sleep(self.delay)
            self.sent.append(text)
        finally:
            self.in_flight -= 1

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def frames(match: str, start: int, count: int, broadcast=None) -> dict[str, object]:
    message = {"type": "live.frames", "match_id": match, "frames": [{"t": t, "p": [], "b": [0, 0, -1, 0]} for t in range(start, start + count)]}
    if broadcast is not None:
        message["broadcast"] = broadcast
    return message


def test_one_writer_per_socket_never_sends_concurrently():
    async def scenario():
        hub = RoomConnectionHub()
        socket = FakeSocket(delay=0.002)
        channel = await hub.connect("room", socket, "FLA")
        await asyncio.gather(*(hub.broadcast("room", {"type": "season.tick", "n": n}) for n in range(30)))
        for n in range(10):
            channel.send_visual(frames("m1", n * 2, 2))
        await asyncio.sleep(0.3)
        return socket
    socket = asyncio.run(scenario())
    assert socket.max_in_flight == 1
    ticks = [json.loads(text)["n"] for text in socket.sent if '"season.tick"' in text]
    assert ticks == list(range(30))  # reliable messages keep their order


def test_frames_are_coalesced_and_bounded_while_the_socket_is_busy():
    async def scenario():
        hub = RoomConnectionHub()
        socket = FakeSocket(delay=0.05)
        channel = await hub.connect("room", socket, "FLA")
        channel.send_reliable({"type": "season.sync"})  # keeps the writer busy for a moment
        segment_a = [{"k": "PLAY", "t0": 0, "t1": 10, "r0": 1.0, "r1": 2.0, "label": ""}]
        segment_b = [{"k": "CUT", "t0": 10, "t1": 90, "r0": 2.0, "r1": 3.0, "label": ""}]
        channel.send_visual(frames("m1", 0, 200, segment_a))
        channel.send_visual(frames("m1", 200, 200, segment_b))
        await asyncio.sleep(0.3)
        return socket
    before = dict(realtime.STATS)
    socket = asyncio.run(scenario())
    visual = [json.loads(text) for text in socket.sent if '"live.frames"' in text]
    assert len(visual) == 1  # one merged message instead of a backlog
    rows = visual[0]["frames"]
    assert len(rows) == MAX_COALESCED_ROWS and rows[-1]["t"] == 399  # newest kept, oldest dropped
    assert [s["r0"] for s in visual[0]["broadcast"]] == [1.0, 2.0]  # pacing segments never lost
    assert realtime.STATS["frames_coalesced"] > before["frames_coalesced"]


def test_reliable_backlog_overflow_asks_for_reconciliation_instead_of_dropping():
    async def scenario():
        hub = RoomConnectionHub()
        socket = FakeSocket(delay=0.001)
        channel = await hub.connect("room", socket, "FLA")
        for n in range(MAX_RELIABLE_QUEUE + 50):  # queued synchronously: the writer cannot drain in between
            channel.send_reliable({"type": "live.state", "seq": n})
        await asyncio.sleep(0.5)
        return socket
    socket = asyncio.run(scenario())
    kinds = [json.loads(text)["type"] for text in socket.sent]
    assert "live.resync" in kinds
    assert len(socket.sent) <= MAX_RELIABLE_QUEUE + 1  # bounded memory


def test_a_permanently_slow_client_is_closed_and_forgotten(monkeypatch):
    monkeypatch.setattr(realtime, "SEND_TIMEOUT", 0.05)

    async def scenario():
        hub = RoomConnectionHub()
        stuck = FakeSocket(stuck=True)
        healthy = FakeSocket()
        await hub.connect("room", stuck, "FLA")
        await hub.connect("room", healthy, "PAL")
        await hub.broadcast("room", {"type": "season.ready_changed"})
        await asyncio.sleep(0.3)
        await hub.broadcast("room", {"type": "season.round_started"})
        await asyncio.sleep(0.05)
        return len(hub.channels("room")), stuck, healthy
    alive, stuck, healthy = asyncio.run(scenario())
    assert stuck.closed_with == 1013  # "try again later": the client reconnects and resyncs
    assert alive == 1
    assert [json.loads(t)["type"] for t in healthy.sent] == ["season.ready_changed", "season.round_started"]


# ---------------------------------------------------------------- sequenced live state
@pytest.fixture
def live_round():
    now = [1_900_000_000.0]
    service = SeasonService(clock=lambda: now[0], intro_seconds=5)
    market = InitialMarket(synthetic_catalog("ELEVEN_A_SIDE", teams=20), "ELEVEN_A_SIDE", dict.fromkeys((c.code for c in CLUBS), 10_000_000_000))
    complete_test_market(market, "seq-fixture")
    service.create("room", market)
    for club in ("FLA", "PAL"):
        service.ready("room", club)
    service.advance("room", market, {"FLA", "PAL"}, 90)
    return service, now


def test_live_state_is_incremental_sequenced_and_never_reveals_the_future(live_round):
    service, now = live_round
    season = service._season("room")
    start = season.live_round["started_at"]
    known = None
    seen: list[str] = []
    for second in range(0, 96, 3):
        now[0] = start + second
        service.sync_live("room")
        message = service.live_state("room", "FLA", known, heartbeat=False)
        if message is None:
            continue
        known = message.pop("_known")
        assert message["seq_from"] == len(seen)  # no gap, no repetition
        seen.extend(event["event_id"] for event in message["events"])
        assert message["seq"] == len(seen)
        shown = message["tick"]
        assert all(event["tick"] <= shown for event in message["events"])  # nothing beyond the screen
        home, away = message["score"]["home"], message["score"]["away"]
        match_id = message["match_id"]
        goals = [e for e in season.engines[match_id].events if e["kind"] == "GOAL" and e["tick"] <= shown]
        assert home + away == len(goals)
    view = service.live_view("room", "FLA")["match"]
    assert [e["event_id"] for e in view["events"]][: len(seen)] == seen  # same events as the HTTP view


def test_live_state_masks_the_rivals_tactics_like_the_http_view(live_round):
    service, now = live_round
    season = service._season("room")
    now[0] = season.live_round["started_at"] + 20
    service.sync_live("room")
    fixture = next(mid for mid in season.live_round["match_ids"] if "FLA" in (season.matches[mid]["home"], season.matches[mid]["away"]))
    rival = season.matches[fixture]["away"] if season.matches[fixture]["home"] == "FLA" else season.matches[fixture]["home"]
    side = 0 if season.matches[fixture]["home"] == rival else 1
    engine = season.engines[fixture]
    engine.queue_tactics(side, engine.tactics[side].replace(mentality="VERY_ATTACKING"), f"{rival}:secret-plan")
    now[0] += 30
    service.sync_live("room")
    message = service.live_state("room", "FLA", None, heartbeat=True)
    masked = [e for e in message["events"] if e["kind"] == "TACTICS" and e["team"] == rival]
    assert masked and all(e["tactics"] is None and e["outcome"] == "CHANGED" for e in masked)


def test_live_stats_are_compact_and_without_events(live_round):
    service, now = live_round
    now[0] = service._season("room").live_round["started_at"] + 30
    service.sync_live("room")
    stats = service.live_stats("room", "FLA")
    assert stats["type"] == "live.stats" and "events" not in stats["match"]
    assert all("attributes" not in player for side in stats["match"]["lineups"].values() for player in side)
    full = json.dumps(service.live_view("room", "FLA"))
    assert len(json.dumps(stats)) < len(full) / 2
