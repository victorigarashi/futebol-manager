"""Coach decisions shared by humans, bots, the match engine and the API."""

from __future__ import annotations

from dataclasses import asdict, dataclass

MENTALITIES: dict[str, str] = {
    "VERY_DEFENSIVE": "Muito defensiva",
    "DEFENSIVE": "Defensiva",
    "BALANCED": "Equilibrada",
    "ATTACKING": "Ofensiva",
    "VERY_ATTACKING": "Muito ofensiva",
}
PRESSURES: dict[str, str] = {"LOW": "Baixa", "MEDIUM": "Média", "HIGH": "Alta"}
STYLES: dict[str, str] = {
    "POSSESSION": "Posse",
    "COUNTER": "Contra-ataque",
    "DIRECT": "Direto",
    "SHORT_BUILDUP": "Construção curta",
    "WIDE": "Pelas laterais",
}

# What each choice changes inside the agent simulation. These texts describe the
# real parameters in match_engine.TACTIC_PROFILES; no goal or rating bonus exists.
EFFECTS: dict[str, dict[str, str]] = {
    "mentality": {
        "VERY_DEFENSIVE": "Linha baixa e bloco curto. Poucos jogadores sobem; menos espaço às costas, menos presença na área rival.",
        "DEFENSIVE": "Linha recuada e laterais contidos. Prioriza proteger a área, aceita menos chegadas.",
        "BALANCED": "Linha média, apoio ofensivo moderado e equilíbrio entre risco e proteção.",
        "ATTACKING": "Linha alta e laterais apoiando. Mais gente na área, mais espaço para transições adversárias.",
        "VERY_ATTACKING": "Bloco todo no campo rival. Máximo apoio e finalizações mais cedo; defesa muito exposta.",
    },
    "pressure": {
        "LOW": "Pressiona só perto da própria área. Poupa energia, cede a bola e o território.",
        "MEDIUM": "Pressiona a partir do meio-campo com um jogador e fecha linhas de passe.",
        "HIGH": "Dois ou três jogadores atacam o portador em qualquer zona. Recupera alto, cansa mais e comete mais faltas.",
    },
    "style": {
        "POSSESSION": "Passes seguros, paciência e circulação. Evita perder a bola, demora mais a chegar.",
        "COUNTER": "Bloco organizado e, ao recuperar, bola rápida às costas da defesa com corredores.",
        "DIRECT": "Bola longa para frente cedo. Ganha metros rápido e erra mais passes.",
        "SHORT_BUILDUP": "Goleiro e zagueiros saem jogando curto. Atrai a pressão, arrisca perda perto do gol.",
        "WIDE": "Time aberto, procura os lados e cruza na área.",
    },
}


@dataclass(frozen=True)
class Tactics:
    mentality: str = "BALANCED"
    pressure: str = "MEDIUM"
    style: str = "POSSESSION"

    def __post_init__(self) -> None:
        if self.mentality not in MENTALITIES:
            raise ValueError("Mentalidade inválida.")
        if self.pressure not in PRESSURES:
            raise ValueError("Pressão inválida.")
        if self.style not in STYLES:
            raise ValueError("Estilo de jogo inválido.")

    def view(self) -> dict[str, str]:
        return asdict(self)

    def replace(self, **changes: str | None) -> Tactics:
        values = self.view()
        values.update({key: value for key, value in changes.items() if value is not None})
        return Tactics(**values)


# Legacy single "strategy" codes from the previous beta map onto the new model so
# saved snapshots and older clients keep working.
LEGACY_STRATEGIES: dict[str, Tactics] = {
    "BALANCED": Tactics(),
    "ATTACKING": Tactics(mentality="ATTACKING"),
    "DEFENSIVE": Tactics(mentality="DEFENSIVE"),
    "COUNTER": Tactics(mentality="DEFENSIVE", style="COUNTER"),
    "POSSESSION": Tactics(style="POSSESSION"),
    "HIGH_PRESS": Tactics(pressure="HIGH"),
}


def tactics_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "mentality": [{"code": c, "name": n, "effect": EFFECTS["mentality"][c]} for c, n in MENTALITIES.items()],
        "pressure": [{"code": c, "name": n, "effect": EFFECTS["pressure"][c]} for c, n in PRESSURES.items()],
        "style": [{"code": c, "name": n, "effect": EFFECTS["style"][c]} for c, n in STYLES.items()],
    }


def tactics_from_payload(payload: object) -> Tactics:
    if isinstance(payload, Tactics):
        return payload
    if isinstance(payload, str):
        if payload not in LEGACY_STRATEGIES:
            raise ValueError("Estratégia inválida.")
        return LEGACY_STRATEGIES[payload]
    if isinstance(payload, dict):
        return Tactics(str(payload.get("mentality", "BALANCED")), str(payload.get("pressure", "MEDIUM")), str(payload.get("style", "POSSESSION")))
    raise ValueError("Tática inválida.")
