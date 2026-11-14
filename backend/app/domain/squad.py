"""Formation definitions and server-authoritative lineup validation."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.catalog import CatalogPlayer
from app.domain.market import MarketError

FORMATION_LINES: dict[str, dict[str, tuple[int, ...]]] = {
    "FIVE_A_SIDE": {"2-1-1": (2, 1, 1), "1-2-1": (1, 2, 1), "2-2": (2, 2), "3-1": (3, 1), "1-3": (1, 3)},
    "ELEVEN_A_SIDE": {
        "4-3-3": (4, 3, 3), "4-4-2": (4, 4, 2), "4-2-3-1": (4, 2, 3, 1),
        "4-1-4-1": (4, 1, 4, 1), "4-2-2-2": (4, 2, 2, 2), "4-3-1-2": (4, 3, 1, 2),
        "3-5-2": (3, 5, 2), "3-4-3": (3, 4, 3), "5-3-2": (5, 3, 2), "5-4-1": (5, 4, 1),
    },
}


@dataclass(frozen=True)
class FormationSlot:
    id: str
    position: str
    x: int
    y: int


def formations(mode: str) -> list[dict[str, object]]:
    if mode not in FORMATION_LINES:
        raise MarketError("Modo de jogo inválido.")
    return [
        {"code": code, "slots": [slot.__dict__ for slot in formation_slots(mode, code)]}
        for code in FORMATION_LINES[mode]
    ]


def formation_slots(mode: str, code: str) -> list[FormationSlot]:
    lines = FORMATION_LINES.get(mode, {}).get(code)
    if not lines:
        raise MarketError("Formação inválida para este modo.")
    slots = [FormationSlot("gk", "GK", 50, 89)]
    line_count = len(lines)
    for line_index, count in enumerate(lines):
        y = round(70 - (line_index * (52 / max(1, line_count - 1)))) if line_count > 1 else 46
        position = "DF" if line_index == 0 else "ST" if line_index == line_count - 1 else "MF"
        for player_index in range(count):
            x = round((player_index + 1) * (100 / (count + 1)))
            slots.append(FormationSlot(f"{position.lower()}-{line_index}-{player_index}", position, x, y))
    return slots


def effective_overall(player: CatalogPlayer, target_position: str) -> tuple[int, bool]:
    """Return a transparent, deterministic rating; no client-supplied rating is trusted."""
    accepted = {player.position, *player.secondary_positions}
    if target_position in accepted:
        return player.overall, False
    penalty = 12 if player.position == "GK" or target_position == "GK" else 6
    return max(1, player.overall - penalty), True


def simulation_overall(player: CatalogPlayer, current_overall: int, target_position: str | None = None) -> int:
    """Apply an optional, bounded position-aware editorial component adjustment.

    Overall remains the career and market rating. Entries without attributes
    (including synthetic and legacy catalog records) keep their exact overall.
    """
    attributes = player.attributes
    if not attributes:
        return max(1, min(99, current_overall))
    position = target_position or player.position
    weights = {
        "GK": {"gk_diving": .30, "gk_handling": .25, "gk_reflexes": .30, "gk_positioning": .15},
        "DF": {"defending": .45, "physical": .25, "pace": .20, "passing": .10},
        "MF": {"passing": .35, "dribbling": .25, "defending": .20, "physical": .10, "pace": .10},
        "ST": {"shooting": .40, "pace": .25, "dribbling": .20, "physical": .15},
    }[position]
    available = [(key, weight) for key, weight in weights.items() if key in attributes]
    if not available:
        return max(1, min(99, current_overall))
    total_weight = sum(weight for _, weight in available)
    component_rating = sum(attributes[key] * weight for key, weight in available) / total_weight
    # Components can move a match rating by at most four points, preserving progression.
    adjustment = round((component_rating - player.overall) * .25)
    return max(1, min(99, current_overall + adjustment))


def validate_lineup(
    *, mode: str, formation_code: str, assignments: dict[str, str], roster: list[str], players: dict[str, CatalogPlayer]
) -> list[dict[str, object]]:
    slots = formation_slots(mode, formation_code)
    slot_ids = {slot.id for slot in slots}
    if set(assignments) != slot_ids:
        raise MarketError("A escalação deve preencher exatamente todas as vagas da formação.")
    player_ids = list(assignments.values())
    if len(player_ids) != len(set(player_ids)):
        raise MarketError("Um atleta não pode ocupar duas vagas.")
    if not set(player_ids).issubset(roster):
        raise MarketError("A escalação deve usar somente os atletas do seu elenco.")
    result: list[dict[str, object]] = []
    for slot in slots:
        player = players.get(assignments[slot.id])
        if not player:
            raise MarketError("Atleta não encontrado no elenco.")
        rating, improvised = effective_overall(player, slot.position)
        if slot.position == "GK" and player.position != "GK" and "GK" not in player.secondary_positions:
            raise MarketError("A formação exige um goleiro na vaga de GK.")
        result.append({"slot_id": slot.id, "player_id": player.id, "target_position": slot.position, "effective_overall": rating, "improvised": improvised})
    return result
