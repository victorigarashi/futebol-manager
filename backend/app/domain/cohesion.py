"""Entrosamento tático: how well a squad fits the chosen way of playing.

Two parts, both deterministic and server-side:

* **Compatibilidade** (0–100) — computed from the starters' attributes, their
  positions in the formation, the existing tactics (style, pressure, mentality) and
  the individual instructions. It measures *fit*, not quality: each player is
  compared with his own overall, so a weaker squad that suits the plan can score
  higher than a stronger one that does not.
* **Familiaridade** (0–100 per style) — grows a little with every official match
  played with that style and fades slowly when the club uses another one.

This is **not** Ultimate Team chemistry: nationality, league and club play no part.

Only six face attributes exist in the catalog (pace, shooting, passing, dribbling,
defending, physical). Players without them use the transparent per-position profile
from ``match_engine.derived_attributes``; their share is reported as ``estimated``
so the interface never presents an estimate as catalog data.

The match engine receives one bounded number per team, ``cohesion`` in [-1, 1]. It
never touches overall, goals or ratings; it only sharpens or blunts execution
(pass accuracy, decision noise, off-ball positioning, pressing duels). See
``docs/ENTROSAMENTO.md`` for the calibration.
"""

from __future__ import annotations

from collections.abc import Mapping

FACE = ("pace", "shooting", "passing", "dribbling", "defending", "physical")

# What each existing style asks of the outfield players (weights sum to 1).
STYLE_WEIGHTS: dict[str, dict[str, float]] = {
    "POSSESSION": {"passing": 0.45, "dribbling": 0.35, "pace": 0.10, "defending": 0.10},
    "COUNTER": {"pace": 0.45, "passing": 0.25, "shooting": 0.20, "defending": 0.10},
    "DIRECT": {"physical": 0.35, "shooting": 0.30, "passing": 0.20, "pace": 0.15},
    "SHORT_BUILDUP": {"passing": 0.50, "dribbling": 0.30, "defending": 0.20},
    "WIDE": {"pace": 0.35, "dribbling": 0.35, "passing": 0.30},
}
# Pressure is a separate axis in the existing tactics; HIGH is "pressão alta",
# LOW with a defensive mentality is the "defesa compacta" of the design document.
PRESSURE_WEIGHTS: dict[str, dict[str, float]] = {
    "HIGH": {"physical": 0.40, "defending": 0.35, "pace": 0.25},
    "MEDIUM": {"defending": 0.40, "physical": 0.30, "pace": 0.30},
    "LOW": {"defending": 0.60, "physical": 0.40},
}
# The share of each player's fit that comes from the style (rest: pressure), by line.
STYLE_SHARE = {"GK": 0.0, "DF": 0.35, "MF": 0.65, "ST": 0.80}

# Individual instructions per slot role. The first one is the default.
INSTRUCTIONS: dict[str, dict[str, dict[str, object]]] = {
    "GK": {
        "LINE": {"name": "Fica na linha", "effect": "Protege o gol e sai pouco.", "needs": {}},
        "SWEEPER": {"name": "Goleiro-líbero", "effect": "Adianta-se para cobrir as costas da defesa.", "needs": {"pace": 0.5, "passing": 0.5}},
    },
    "FB": {
        "SUPPORT": {"name": "Apoiar o ataque", "effect": "Sobe quando o time tem a bola, volta na perda.", "needs": {"pace": 0.5, "passing": 0.5}},
        "STAY_BACK": {"name": "Ficar na defesa", "effect": "Segura a posição e fecha o corredor.", "needs": {"defending": 0.7, "physical": 0.3}},
        "OVERLAP": {"name": "Avançar frequentemente", "effect": "Passa do ponta e chega à linha de fundo.", "needs": {"pace": 0.6, "dribbling": 0.2, "physical": 0.2}},
    },
    "CB": {
        "COVER": {"name": "Cobertura", "effect": "Prioriza a proteção da área.", "needs": {"defending": 0.7, "physical": 0.3}},
        "BALL_PLAYING": {"name": "Sair jogando", "effect": "Procura o passe vertical na saída de bola.", "needs": {"passing": 0.7, "defending": 0.3}},
    },
    "MF": {
        "BALANCED": {"name": "Equilibrado", "effect": "Ataca e defende conforme a jogada.", "needs": {"passing": 0.5, "defending": 0.25, "physical": 0.25}},
        "HOLD": {"name": "Proteger a defesa", "effect": "Fica à frente da zaga e corta as transições.", "needs": {"defending": 0.6, "physical": 0.4}},
        "ARRIVE": {"name": "Chegar à área", "effect": "Infiltra na área nas jogadas de ataque.", "needs": {"shooting": 0.4, "pace": 0.3, "physical": 0.3}},
    },
    "ST": {
        "COMPLETE": {"name": "Centroavante", "effect": "Finaliza e participa da construção.", "needs": {"shooting": 0.6, "physical": 0.2, "pace": 0.2}},
        "FALSE_9": {"name": "Falso 9", "effect": "Recua para receber e abre espaço para quem chega.", "needs": {"passing": 0.5, "dribbling": 0.5}},
        "TARGET": {"name": "Pivô", "effect": "Segura a bola de costas e recebe lançamentos.", "needs": {"physical": 0.7, "shooting": 0.3}},
        "IN_BEHIND": {"name": "Atacar profundidade", "effect": "Corre às costas da defesa o tempo todo.", "needs": {"pace": 0.7, "shooting": 0.3}},
    },
}


def slot_role(position: str, slot_x: float, line_size: int) -> str:
    """GK, FB (wide defender), CB, MF or ST from the formation slot."""
    if position == "DF":
        wide = line_size >= 4 and (slot_x <= 25 or slot_x >= 75)
        return "FB" if wide else "CB"
    return position


def default_instruction(role: str) -> str:
    return next(iter(INSTRUCTIONS[role]))


def validate_instruction(role: str, code: str) -> str:
    if role not in INSTRUCTIONS or code not in INSTRUCTIONS[role]:
        raise ValueError("Instrução individual inválida para esta posição.")
    return code


def instruction_catalog() -> dict[str, list[dict[str, str]]]:
    return {role: [{"code": code, "name": str(spec["name"]), "effect": str(spec["effect"])} for code, spec in options.items()]
            for role, options in INSTRUCTIONS.items()}


def _weighted(attrs: Mapping[str, float], weights: Mapping[str, float]) -> float:
    return sum(attrs.get(key, 0.0) * weight for key, weight in weights.items()) / (sum(weights.values()) or 1.0)


def _fit_points(rating: float, overall: float) -> float:
    """Fit on a 0–100 scale: 50 when the profile matches the player's own level."""
    return max(0.0, min(100.0, 50.0 + 3.0 * (rating - overall)))


def compatibility(starters: list[dict[str, object]], style: str, pressure: str, mentality: str) -> dict[str, object]:
    """Compatibility of a starting eleven (or five) with the tactics.

    ``starters`` rows: ``attributes`` (6 face values), ``overall``, ``slot_position``,
    ``natural`` (bool: playing in an accepted position), ``role`` (slot_role),
    ``instruction`` (code) and ``estimated`` (bool: attributes derived, not catalog).
    """
    if not starters:
        return {"score": 0, "players": [], "estimated_share": 0.0, "notes": []}
    style_w = STYLE_WEIGHTS[style]
    press_w = PRESSURE_WEIGHTS[pressure]
    rows = []
    for row in starters:
        attrs = row["attributes"]
        overall = float(row["overall"])  # type: ignore[arg-type]
        pos = str(row["slot_position"])
        if pos == "GK":
            keeper = float(attrs.get("keeping", overall))  # type: ignore[union-attr]
            fit = _fit_points(keeper, overall)
            if row["instruction"] == "SWEEPER":
                fit = 0.7 * fit + 0.3 * _fit_points(_weighted(attrs, INSTRUCTIONS["GK"]["SWEEPER"]["needs"]) + 20, overall)  # type: ignore[arg-type]
        else:
            share = STYLE_SHARE.get(pos, 0.5)
            fit_style = _fit_points(_weighted(attrs, style_w), overall)  # type: ignore[arg-type]
            fit_press = _fit_points(_weighted(attrs, press_w), overall)  # type: ignore[arg-type]
            fit = share * fit_style + (1 - share) * fit_press
            needs = INSTRUCTIONS[str(row["role"])][str(row["instruction"])]["needs"]
            if needs:
                fit = 0.75 * fit + 0.25 * _fit_points(_weighted(attrs, needs), overall)  # type: ignore[arg-type]
        if not row["natural"]:
            fit -= 18.0  # improvised players do not know the movements of the role
        rows.append({"player_id": row.get("player_id"), "fit": round(max(0.0, min(100.0, fit)), 1), "estimated": bool(row["estimated"])})
    score = sum(r["fit"] for r in rows) / len(rows)
    notes: list[str] = []
    # Balance of the squad: a plan needs bodies in the right places.
    roles = [str(r["role"]) for r in starters]
    instructions = [str(r["instruction"]) for r in starters]
    if style == "WIDE" and "FB" not in roles and mentality in ("DEFENSIVE", "VERY_DEFENSIVE"):
        score -= 6
        notes.append("Jogo pelas pontas sem laterais e com mentalidade defensiva: pouca gente abre o campo.")
    if pressure == "HIGH" and mentality in ("VERY_DEFENSIVE",):
        score -= 5
        notes.append("Pressão alta com bloco muito recuado: as linhas ficam distantes.")
    if instructions.count("OVERLAP") >= 2 and instructions.count("HOLD") == 0:
        score -= 4
        notes.append("Dois laterais avançando sem volante de proteção: costas expostas.")
    if instructions.count("FALSE_9") and not any(code in ("ARRIVE", "IN_BEHIND") for code in instructions):
        score -= 3
        notes.append("Falso 9 sem ninguém para atacar o espaço que ele abre.")
    estimated = sum(1 for r in rows if r["estimated"]) / len(rows)
    return {"score": round(max(0.0, min(100.0, score)), 1), "players": rows, "estimated_share": round(estimated, 2), "notes": notes}


# ---------------------------------------------------------------- familiarity
FAMILIARITY_START = 30.0
FAMILIARITY_GAIN = 0.08     # share of the remaining distance to 100 gained per match
FAMILIARITY_FADE = 0.6      # points lost per match by every style not used
FAMILIARITY_FLOOR = 20.0    # what a club never forgets about a style it has used


def familiarity_after_match(current: Mapping[str, float], used_style: str) -> dict[str, float]:
    updated = {style: float(current.get(style, FAMILIARITY_START)) for style in STYLE_WEIGHTS}
    for style, value in updated.items():
        if style == used_style:
            updated[style] = round(value + (100.0 - value) * FAMILIARITY_GAIN, 2)
        else:
            updated[style] = round(max(min(value, FAMILIARITY_FLOOR), value - FAMILIARITY_FADE), 2)
    return updated


def familiarity_of(current: Mapping[str, float], style: str) -> float:
    return float(current.get(style, FAMILIARITY_START))


def cohesion_factor(compat: float, familiarity: float) -> float:
    """The single bounded number the engine uses, in [-1, 1].

    Compatibility weighs 60 %, familiarity 40 %; both centred on 50."""
    value = 0.6 * (compat - 50.0) / 50.0 + 0.4 * (familiarity - 50.0) / 50.0
    return round(max(-1.0, min(1.0, value)), 3)


def level_label(score: float) -> str:
    if score >= 75:
        return "Excelente"
    if score >= 60:
        return "Bom"
    if score >= 45:
        return "Regular"
    return "Baixo"
