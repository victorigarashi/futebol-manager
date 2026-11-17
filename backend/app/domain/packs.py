"""Pack & Play: free packs of real catalog athletes, a temporary collection, a squad.

Rules (documented in docs/MODOS_NOVOS.md):

* Packs are a free mechanic of the room. There is no purchase, no currency and nothing
  carries over: the collection exists only in this room and never touches the career.
* Cards are real catalog athletes (synthetic records are never offered); ratings are
  never changed.
* **Quality tiers** by overall within the chosen catalog: Ouro = top 15 %, Prata = next
  35 %, Bronze = the remaining 50 %.
  - ``BALANCED`` (default): every collection has exactly the same number of cards of
    each tier (15 % / 35 % / 50 %, rounded), shuffled across positions and packs.
  - ``LUCK``: every card's tier is drawn independently with those probabilities.
* **Positions guaranteed**: each collection has a fixed composition that always allows
  a valid squad (11-a-side: 3 GK, 8 DF, 7 MF, 5 ST, 1 any = 24 cards in 4 packs of 6;
  5-a-side: 2 GK, 4 DF, 3 MF, 2 ST, 1 any = 12 cards in 3 packs of 4).
* No athlete appears twice in one collection; different managers may get the same
  athlete — each squad then holds its own independent instance.
* Everything is drawn from a generator seeded by (room, club): opening the packs again
  (refresh, reconnection) shows exactly the same cards.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import asdict, dataclass, field

from app.domain.catalog import CatalogPlayer
from app.domain.draft import BENCH_SIZE, eligible_pool, fits
from app.domain.squad import FORMATION_LINES, formation_slots

TIERS = ("OURO", "PRATA", "BRONZE")
TIER_SHARE = {"OURO": 0.15, "PRATA": 0.35, "BRONZE": 0.50}
COMPOSITION = {
    "ELEVEN_A_SIDE": {"packs": 4, "per_pack": 6, "positions": {"GK": 3, "DF": 8, "MF": 7, "ST": 5, "ANY": 1}},
    "FIVE_A_SIDE": {"packs": 3, "per_pack": 4, "positions": {"GK": 2, "DF": 4, "MF": 3, "ST": 2, "ANY": 1}},
}
LUCK_MODES = ("BALANCED", "LUCK")


class PackError(ValueError):
    pass


def tier_of(pool: list[CatalogPlayer]) -> dict[str, str]:
    """Tier of every pool athlete by overall rank (ties broken by id, stable)."""
    ranked = sorted(pool, key=lambda p: (-p.overall, p.id))
    n = len(ranked)
    gold, silver = round(n * TIER_SHARE["OURO"]), round(n * (TIER_SHARE["OURO"] + TIER_SHARE["PRATA"]))
    return {p.id: "OURO" if i < gold else "PRATA" if i < silver else "BRONZE" for i, p in enumerate(ranked)}


def _tier_plan(total: int, luck: str, rng: random.Random) -> list[str]:
    if luck == "LUCK":
        return [rng.choices(TIERS, weights=[TIER_SHARE[t] for t in TIERS])[0] for _ in range(total)]
    gold = round(total * TIER_SHARE["OURO"])
    silver = round(total * TIER_SHARE["PRATA"])
    plan = ["OURO"] * gold + ["PRATA"] * silver + ["BRONZE"] * (total - gold - silver)
    rng.shuffle(plan)
    return plan


def open_packs(seed_text: str, mode: str, catalog: list[CatalogPlayer], luck: str = "BALANCED") -> list[list[str]]:
    """The packs of one manager: lists of catalog ids (deterministic from the seed)."""
    if luck not in LUCK_MODES:
        raise PackError("Distribuição de pacotes inválida.")
    shape = COMPOSITION[mode]
    pool = eligible_pool(catalog, 0)
    tiers = tier_of(pool)
    rng = random.Random(zlib.crc32(seed_text.encode()))
    slots = [pos for pos, count in shape["positions"].items() for _ in range(count)]
    rng.shuffle(slots)
    # Goalkeepers are spread across packs so the first pack already has one.
    slots.sort(key=lambda pos: 0 if pos == "GK" else 1)
    gk = [s for s in slots if s == "GK"]
    rest = [s for s in slots if s != "GK"]
    ordered = []
    packs_n, per_pack = shape["packs"], shape["per_pack"]
    for _pack in range(packs_n):
        chunk = [gk.pop(0)] if gk else []
        while len(chunk) < per_pack and rest:
            chunk.append(rest.pop(0))
        ordered.append(chunk)
    for leftover in gk + rest:  # never lose a guaranteed position
        min(ordered, key=len).append(leftover)
    plan = iter(_tier_plan(sum(len(p) for p in ordered), luck, rng))
    taken: set[str] = set()
    packs: list[list[str]] = []
    for chunk in ordered:
        cards = []
        for pos in chunk:
            tier = next(plan)
            order = [tier] + [t for t in TIERS if t != tier]
            card = None
            for wanted in order:  # an exhausted tier falls back to the nearest one
                options = [p for p in pool if p.id not in taken and tiers[p.id] == wanted and (pos == "ANY" or p.position == pos)]
                if options:
                    card = rng.choice(sorted(options, key=lambda p: p.id))
                    break
            if card is None:
                raise PackError("O catálogo não tem atletas suficientes para montar os pacotes.")
            taken.add(card.id)
            cards.append(card.id)
        # The best card of the pack is revealed last (the highlight of the animation).
        cards.sort(key=lambda cid: next(p.overall for p in pool if p.id == cid))
        packs.append(cards)
    return packs


@dataclass
class PackCollection:
    club: str
    packs: list[list[str]]
    opened: int = 0
    formation: str | None = None
    slots: dict[str, str | None] = field(default_factory=dict)   # slot id -> catalog id
    bench: list[str] = field(default_factory=list)
    confirmed: bool = False
    auto_completed: bool = False

    @property
    def cards(self) -> list[str]:
        return [cid for pack in self.packs for cid in pack]


@dataclass
class PackState:
    room_id: str
    mode: str
    catalog_name: str
    luck: str
    clubs: dict[str, PackCollection]
    deadline: float | None = None
    completed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {**{k: v for k, v in asdict(self).items() if k != "clubs"}, "clubs": {c: asdict(s) for c, s in self.clubs.items()}}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> PackState:
        clubs = {str(c): PackCollection(**dict(s)) for c, s in dict(raw["clubs"]).items()}
        state = cls(str(raw["room_id"]), str(raw["mode"]), str(raw["catalog_name"]), str(raw.get("luck", "BALANCED")), clubs,
                    raw.get("deadline"), bool(raw.get("completed", False)))
        for col in clubs.values():
            owned = set(col.cards)
            if not set(filter(None, col.slots.values())) <= owned or not set(col.bench) <= owned:
                raise ValueError("Snapshot do Pack & Play contém carta fora da coleção.")
        return state


class Packs:
    """Rules over a PackState (callers hold the room lock)."""

    def __init__(self, state: PackState, catalog: list[CatalogPlayer]) -> None:
        self.state = state
        self.catalog = {p.id: p for p in catalog}

    def collection(self, club: str) -> PackCollection:
        if club not in self.state.clubs:
            raise PackError("Seu clube não participa deste Pack & Play.")
        return self.state.clubs[club]

    def open_next(self, club: str) -> list[str]:
        col = self.collection(club)
        if col.opened < len(col.packs):
            col.opened += 1
        return col.packs[col.opened - 1] if col.opened else []

    def set_formation(self, club: str, code: str) -> None:
        col = self.collection(club)
        if col.confirmed or self.state.completed:
            raise PackError("O elenco já foi confirmado.")
        if code not in FORMATION_LINES[self.state.mode]:
            raise PackError("Formação inválida para este modo.")
        col.formation = code
        col.slots = {slot.id: None for slot in formation_slots(self.state.mode, code)}
        col.bench = []

    def place(self, club: str, slot_id: str, catalog_id: str | None) -> None:
        """Put a card of the collection in a starting slot (None empties it)."""
        col = self.collection(club)
        if col.confirmed or self.state.completed:
            raise PackError("O elenco já foi confirmado.")
        if col.opened < len(col.packs):
            raise PackError("Abra todos os pacotes antes de montar o time.")
        if slot_id not in col.slots:
            raise PackError("Posição inexistente nesta formação.")
        if catalog_id is not None:
            if catalog_id not in col.cards:
                raise PackError("Essa carta não está na sua coleção.")
            for other, cid in col.slots.items():
                if cid == catalog_id and other != slot_id:
                    col.slots[other] = None  # moving a card frees its old slot
            if catalog_id in col.bench:
                col.bench.remove(catalog_id)
        col.slots[slot_id] = catalog_id

    def set_bench(self, club: str, catalog_ids: list[str]) -> None:
        col = self.collection(club)
        if col.confirmed or self.state.completed:
            raise PackError("O elenco já foi confirmado.")
        starters = set(filter(None, col.slots.values()))
        size = BENCH_SIZE[self.state.mode]
        if len(catalog_ids) != len(set(catalog_ids)) or len(catalog_ids) > size:
            raise PackError(f"O banco tem até {size} atletas, sem repetir.")
        if not set(catalog_ids) <= set(col.cards) or set(catalog_ids) & starters:
            raise PackError("Reservas precisam ser cartas da coleção fora do time titular.")
        col.bench = list(catalog_ids)

    def slot_position(self, club: str, slot_id: str) -> str:
        col = self.collection(club)
        return next(s.position for s in formation_slots(self.state.mode, str(col.formation)) if s.id == slot_id)

    def problems(self, club: str) -> list[str]:
        col = self.collection(club)
        issues = []
        if not col.formation:
            issues.append("Escolha uma formação.")
        if any(cid is None for cid in col.slots.values()):
            issues.append("Preencha todas as posições titulares.")
        if len(col.bench) < BENCH_SIZE[self.state.mode]:
            issues.append(f"Escolha {BENCH_SIZE[self.state.mode]} reservas.")
        keepers = [cid for slot, cid in col.slots.items() if cid and self.slot_position(club, slot) == "GK"]
        if col.formation and keepers and not fits(self.catalog[keepers[0]], "GK"):
            issues.append("O gol precisa de um goleiro.")
        return issues

    def confirm(self, club: str) -> None:
        issues = self.problems(club)
        if issues:
            raise PackError(" ".join(issues))
        self.collection(club).confirmed = True

    def auto_complete(self, club: str, difficulty: str = "COMPETITIVE") -> None:
        """Bots (and absent managers at the deadline) build the best squad they can."""
        col = self.collection(club)
        col.opened = len(col.packs)
        if not col.formation:
            col.formation = next(iter(FORMATION_LINES[self.state.mode]))
            col.slots = {slot.id: None for slot in formation_slots(self.state.mode, col.formation)}
        used = set(filter(None, col.slots.values()))
        cards = sorted((self.catalog[c] for c in col.cards), key=lambda p: (-p.overall, p.id))
        careless = difficulty == "CASUAL"
        for slot in formation_slots(self.state.mode, col.formation):
            if col.slots.get(slot.id):
                continue
            options = [p for p in cards if p.id not in used and fits(p, slot.position)] or [p for p in cards if p.id not in used and slot.position != "GK" and p.position != "GK"]
            if not options:
                options = [p for p in cards if p.id not in used]
            pick = options[min(1, len(options) - 1)] if careless and len(options) > 1 else options[0]
            col.slots[slot.id] = pick.id
            used.add(pick.id)
        size = BENCH_SIZE[self.state.mode]
        remaining = [p for p in cards if p.id not in used and p.id not in col.bench]
        keeper = next((p for p in remaining if p.position == "GK"), None)
        bench = list(col.bench)
        if keeper and not any(self.catalog[c].position == "GK" for c in bench):
            bench.append(keeper.id)
        for p in remaining:
            if len(bench) >= size:
                break
            if p.id not in bench:
                bench.append(p.id)
        col.bench = bench[:size]
        col.confirmed = True

    def collection_view(self, club: str) -> dict[str, object]:
        col = self.collection(club)
        pool = eligible_pool(list(self.catalog.values()), 0)
        tiers = tier_of(pool)
        def card(cid: str) -> dict[str, object]:
            p = self.catalog[cid]
            return {"id": p.id, "name": p.name, "position": p.position, "secondary_positions": list(p.secondary_positions),
                    "overall": p.overall, "club_code": p.club_code, "photo_url": p.photo_url, "tier": tiers.get(p.id, "BRONZE"),
                    "attributes": p.attributes}
        visible = col.packs[: col.opened]
        return {"club": club, "packs_total": len(col.packs), "opened": col.opened, "packs": [[card(c) for c in pack] for pack in visible],
                "formation": col.formation, "slots": col.slots, "bench": col.bench, "confirmed": col.confirmed,
                "bench_size": BENCH_SIZE[self.state.mode], "problems": self.problems(club) if col.opened == len(col.packs) else [],
                "formations": list(FORMATION_LINES[self.state.mode])}
