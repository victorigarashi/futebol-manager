"""Modo Draft: squads built from three-card offers, with repeatable athletes.

Rules (see docs/MODO_DRAFT.md):

* Each manager picks a formation, then fills every slot. Asking for a slot returns
  exactly three cards of athletes compatible with that slot (primary or secondary
  position). The offer is stored: asking again returns the same three cards, so
  nobody can re-roll by clicking. A pick must be one of the three, and a confirmed
  pick is final.
* After the starters, the bench (5 in 11-a-side, 3 in 5-a-side) is free: each bench
  offer has three cards of any position.
* **Repeatable athletes.** The same catalog athlete can be in several squads. Every
  pick creates its own *instance* (``DFT-<club>-<nn>-<catalog id>``) that carries a
  copy of the catalog data and the original id; nothing mutable is shared. Within
  one squad an athlete appears at most once, and an offer never repeats an athlete.
* **Balanced draw.** The eligible athletes of a position are split into three
  quality tiers by overall (top, middle, bottom third). Every offer has one card per
  tier, drawn from a generator seeded by (room, club, pick). Every manager therefore
  sees a top-tier card in every single offer; the overall of the cards still varies.
  If a tier runs out (small pools, high minimum overall), the next tier fills in —
  the fallback is recorded in the offer.
* **Minimum overall** filters the pool for humans and bots alike; ratings are never
  changed. A configuration that cannot fill every position is refused, and the
  highest feasible minimum is suggested.
* Synthetic records are never offered as real athletes: the pool only contains
  catalog entries whose source is not synthetic.
* Bots draft with the same offers; their difficulty only changes how they choose.
* At the deadline, every missing pick of an absent manager is made automatically.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import asdict, dataclass, field

from app.domain.catalog import CatalogPlayer
from app.domain.squad import FORMATION_LINES, formation_slots

BENCH_SIZE = {"ELEVEN_A_SIDE": 5, "FIVE_A_SIDE": 3}
SYNTHETIC_SOURCES = {"synthetic-career", "synthetic-demo", "test-fixture"}
NEIGHBOURS = {"DF": ("MF",), "MF": ("DF", "ST"), "ST": ("MF",), "GK": ()}


class DraftError(ValueError):
    pass


def eligible_pool(catalog: list[CatalogPlayer], min_overall: int) -> list[CatalogPlayer]:
    return sorted((p for p in catalog if p.source not in SYNTHETIC_SOURCES and p.overall >= min_overall),
                  key=lambda p: (-p.overall, p.id))


def fits(player: CatalogPlayer, position: str) -> bool:
    return position in (player.position, *player.secondary_positions)


def requirements(mode: str) -> dict[str, int]:
    """Distinct athletes needed per position so any formation can always be offered
    three different cards, even for the last slot of that position."""
    most = {"GK": 1, "DF": 0, "MF": 0, "ST": 0}
    for code in FORMATION_LINES[mode]:
        counts: dict[str, int] = {}
        for slot in formation_slots(mode, code):
            counts[slot.position] = counts.get(slot.position, 0) + 1
        for position, count in counts.items():
            most[position] = max(most[position], count)
    return {position: count + 2 for position, count in most.items()}


def feasibility(catalog: list[CatalogPlayer], mode: str, min_overall: int) -> list[str]:
    pool = eligible_pool(catalog, min_overall)
    problems = []
    for position, needed in requirements(mode).items():
        available = sum(1 for p in pool if fits(p, position))
        if available < needed:
            problems.append(f"{position}: {available} atletas elegíveis, são necessários {needed}.")
    starters = 11 if mode == "ELEVEN_A_SIDE" else 5
    if len(pool) < starters + BENCH_SIZE[mode] + 2:
        problems.append("Atletas insuficientes para completar titulares e reservas.")
    return problems


def best_feasible_minimum(catalog: list[CatalogPlayer], mode: str, options: tuple[int, ...]) -> int | None:
    feasible = [value for value in options if not feasibility(catalog, mode, value)]
    return max(feasible) if feasible else None


@dataclass
class DraftSquad:
    club: str
    formation: str | None = None
    slots: dict[str, str | None] = field(default_factory=dict)   # slot id -> instance id
    bench: list[str] = field(default_factory=list)               # instance ids
    offers: dict[str, list[str]] = field(default_factory=dict)   # offer key -> catalog ids
    offer_notes: dict[str, str] = field(default_factory=dict)
    picks: int = 0
    auto_completed: bool = False

    def instances_used(self, instances: dict[str, dict[str, object]]) -> set[str]:
        ids = [i for i in self.slots.values() if i] + self.bench
        return {str(instances[i]["catalog_id"]) for i in ids}


@dataclass
class DraftState:
    room_id: str
    mode: str
    catalog_name: str
    min_overall: int
    clubs: dict[str, DraftSquad]
    deadline: float | None = None
    instances: dict[str, dict[str, object]] = field(default_factory=dict)  # instance id -> card + owner
    completed: bool = False

    # ------------------------------------------------------------------ helpers
    def bench_size(self) -> int:
        return BENCH_SIZE[self.mode]

    def squad(self, club: str) -> DraftSquad:
        if club not in self.clubs:
            raise DraftError("Seu clube não participa deste Draft.")
        return self.clubs[club]

    def is_complete(self, club: str) -> bool:
        squad = self.clubs[club]
        return bool(squad.formation) and all(squad.slots.values()) and len(squad.bench) >= self.bench_size()

    def to_dict(self) -> dict[str, object]:
        return {**{k: v for k, v in asdict(self).items() if k != "clubs"}, "clubs": {c: asdict(s) for c, s in self.clubs.items()}}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> DraftState:
        clubs = {str(c): DraftSquad(**dict(s)) for c, s in dict(raw["clubs"]).items()}
        state = cls(str(raw["room_id"]), str(raw["mode"]), str(raw["catalog_name"]), int(raw["min_overall"]), clubs,
                    raw.get("deadline"), dict(raw.get("instances", {})), bool(raw.get("completed", False)))
        for squad in clubs.values():
            for instance in [*filter(None, squad.slots.values()), *squad.bench]:
                if instance not in state.instances or state.instances[instance]["owner"] != squad.club:
                    raise ValueError("Snapshot do Draft contém instância de atleta inválida.")
        return state


class Draft:
    """Pure rules over a DraftState and the room's catalog (callers hold the room lock)."""

    def __init__(self, state: DraftState, catalog: list[CatalogPlayer]) -> None:
        self.state = state
        self.catalog = {p.id: p for p in catalog}
        self.pool = eligible_pool(catalog, state.min_overall)

    # ------------------------------------------------------------------ formation
    def set_formation(self, club: str, code: str) -> DraftSquad:
        squad = self.state.squad(club)
        if self.state.completed:
            raise DraftError("O Draft já terminou.")
        if code not in FORMATION_LINES[self.state.mode]:
            raise DraftError("Formação inválida para este modo.")
        if any(squad.slots.values()) or squad.bench:
            raise DraftError("A formação fica definida depois da primeira escolha.")
        squad.formation = code
        squad.slots = {slot.id: None for slot in formation_slots(self.state.mode, code)}
        squad.offers.clear()
        squad.offer_notes.clear()
        return squad

    def slot_position(self, club: str, slot_id: str) -> str | None:
        squad = self.state.squad(club)
        if slot_id.startswith("bench-"):
            return None
        if not squad.formation:
            raise DraftError("Escolha a formação antes de montar o time.")
        for slot in formation_slots(self.state.mode, squad.formation):
            if slot.id == slot_id:
                return slot.position
        raise DraftError("Posição inexistente nesta formação.")

    # ------------------------------------------------------------------ offers
    def offer(self, club: str, slot_id: str) -> list[CatalogPlayer]:
        """The three cards for a slot (created once, then always the same)."""
        squad = self.state.squad(club)
        if self.state.completed:
            raise DraftError("O Draft já terminou.")
        bench = slot_id.startswith("bench-")
        if bench:
            if not squad.formation or not all(squad.slots.values()):
                raise DraftError("Complete os titulares antes de escolher os reservas.")
            index = int(slot_id.split("-")[1]) if slot_id.split("-")[1].isdigit() else -1
            if index != len(squad.bench) + 1 or len(squad.bench) >= self.state.bench_size():
                raise DraftError("Escolha os reservas em ordem.")
        else:
            position = self.slot_position(club, slot_id)
            if squad.slots.get(slot_id):
                raise DraftError("Esta posição já foi preenchida.")
        key = slot_id
        if key not in squad.offers:
            squad.offers[key], note = self._draw(club, key, None if bench else position, squad)
            if note:
                squad.offer_notes[key] = note
        return [self.catalog[pid] for pid in squad.offers[key]]

    def _draw(self, club: str, key: str, position: str | None, squad: DraftSquad) -> tuple[list[str], str | None]:
        used = squad.instances_used(self.state.instances)
        candidates = [p for p in self.pool if p.id not in used and (position is None or fits(p, position))]
        note = None
        if position and len(candidates) < 3:
            # Fallback (documented): neighbouring positions, never an outfield player in goal.
            extra = [p for p in self.pool if p.id not in used and p not in candidates
                     and any(fits(p, n) for n in NEIGHBOURS[position])]
            candidates += extra
            note = "Poucos atletas elegíveis nesta posição: cartas de posições vizinhas incluídas."
        if position == "GK":
            candidates = [p for p in candidates if fits(p, "GK")]
        if len(candidates) < 3:
            raise DraftError("Não há atletas elegíveis suficientes para esta posição com o overall mínimo escolhido.")
        rng = random.Random(zlib.crc32(f"{self.state.room_id}:{club}:{key}:{squad.picks}".encode()))
        ordered = sorted(candidates, key=lambda p: (-p.overall, p.id))
        third = max(1, len(ordered) // 3)
        tiers = [ordered[:third], ordered[third:2 * third], ordered[2 * third:]]
        cards: list[CatalogPlayer] = []
        for index in range(3):
            pool = [p for p in tiers[index] if p not in cards]
            if not pool:  # tier exhausted: take from the closest tier that still has cards
                pool = [p for tier in (tiers[index - 1] if index else [], *tiers) for p in tier if p not in cards]
                note = note or "Faixa de qualidade sem atletas: completada pela faixa vizinha."
            cards.append(rng.choice(pool))
        rng.shuffle(cards)
        return [p.id for p in cards], note

    # ------------------------------------------------------------------ picks
    def pick(self, club: str, slot_id: str, catalog_id: str) -> dict[str, object]:
        squad = self.state.squad(club)
        if self.state.completed:
            raise DraftError("O Draft já terminou.")
        if slot_id not in squad.offers:
            raise DraftError("Abra a posição para ver as cartas antes de escolher.")
        if catalog_id not in squad.offers[slot_id]:
            raise DraftError("Escolha uma das três cartas oferecidas.")
        bench = slot_id.startswith("bench-")
        if not bench and squad.slots.get(slot_id):
            raise DraftError("Esta posição já foi preenchida; escolhas confirmadas não mudam.")
        if catalog_id in squad.instances_used(self.state.instances):
            raise DraftError("Este atleta já está no seu elenco.")
        squad.picks += 1
        instance_id = f"DFT-{club}-{squad.picks:02d}-{catalog_id}"
        card = self.catalog[catalog_id]
        self.state.instances[instance_id] = {"instance_id": instance_id, "catalog_id": catalog_id, "owner": club,
                                             "slot": slot_id, "card": card.model_dump(mode="json")}
        if bench:
            squad.bench.append(instance_id)
        else:
            squad.slots[slot_id] = instance_id
        squad.offers.pop(slot_id, None)
        squad.offer_notes.pop(slot_id, None)
        return self.state.instances[instance_id]

    # ------------------------------------------------------------------ automatic picks
    def next_open_slot(self, club: str) -> str | None:
        squad = self.state.squad(club)
        for slot_id, instance in squad.slots.items():
            if not instance:
                return slot_id
        if len(squad.bench) < self.state.bench_size():
            return f"bench-{len(squad.bench) + 1}"
        return None

    def auto_complete(self, club: str, difficulty: str = "COMPETITIVE") -> None:
        """Bots, and absent managers at the deadline: same offers, decision by difficulty."""
        squad = self.state.squad(club)
        if not squad.formation:
            default = "4-3-3" if self.state.mode == "ELEVEN_A_SIDE" else "2-1-1"
            self.set_formation(club, default)
        while (slot_id := self.next_open_slot(club)) is not None:
            cards = self.offer(club, slot_id)
            self.pick(club, slot_id, self.choose(club, slot_id, cards, difficulty).id)

    def choose(self, club: str, slot_id: str, cards: list[CatalogPlayer], difficulty: str) -> CatalogPlayer:
        squad = self.state.squad(club)
        rng = random.Random(zlib.crc32(f"{self.state.room_id}:{club}:{slot_id}:choose".encode()))
        if difficulty == "CASUAL" and rng.random() < 0.5:
            return rng.choice(cards)
        if slot_id.startswith("bench-"):
            owned = [self.catalog[str(self.state.instances[i]["catalog_id"])] for i in [*filter(None, squad.slots.values()), *squad.bench]]
            has_backup_gk = any(p.position == "GK" for p in owned[len(squad.slots):])
            if difficulty != "CASUAL" and not has_backup_gk and len(squad.bench) == self.state.bench_size() - 1:
                keeper = [c for c in cards if c.position == "GK"]
                if keeper:
                    return keeper[0]
        def value(card: CatalogPlayer) -> float:
            score = float(card.overall)
            if difficulty == "LEGENDARY":
                score += 0.1 * (card.potential - card.overall) + (0.5 if card.attributes else 0.0)
            return score
        return max(cards, key=lambda c: (value(c), c.id))

    # ------------------------------------------------------------------ result
    def roster_players(self, club: str) -> list[CatalogPlayer]:
        """Instances as catalog players of their own (independent ids and state)."""
        squad = self.state.squad(club)
        players = []
        for instance_id in [*filter(None, squad.slots.values()), *squad.bench]:
            instance = self.state.instances[instance_id]
            card = dict(instance["card"])
            card["id"] = instance_id
            card["source_ids"] = {**dict(card.get("source_ids") or {}), "catalog_id": str(instance["catalog_id"]), "draft_owner": club}
            players.append(CatalogPlayer.model_validate(card))
        return players

    def lineup(self, club: str) -> tuple[str, dict[str, str]]:
        squad = self.state.squad(club)
        return str(squad.formation), {slot: str(instance) for slot, instance in squad.slots.items()}

    def balance_report(self) -> dict[str, float]:
        """Mean overall of the best card of each offer made so far, per club (for tests/docs)."""
        best: dict[str, list[int]] = {}
        for instance in self.state.instances.values():
            best.setdefault(str(instance["owner"]), []).append(int(dict(instance["card"])["overall"]))
        return {club: sum(values) / len(values) for club, values in best.items() if values}
