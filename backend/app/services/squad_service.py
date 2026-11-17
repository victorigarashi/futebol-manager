"""In-memory squad lineups, kept separate from the market rules."""

from __future__ import annotations

from app.domain.cohesion import instruction_catalog
from app.domain.market import InitialMarket, MarketError
from app.domain.squad import formation_slots, formations, validate_lineup
from app.domain.tactics import LEGACY_STRATEGIES, Tactics, tactics_catalog, tactics_from_payload
from app.services.market_service import market_service


class SquadService:
    def __init__(self) -> None:
        self._lineups: dict[tuple[str, str], dict[str, object]] = {}
        self._strategies: dict[tuple[str, str], str] = {}
        self._tactics: dict[tuple[str, str], Tactics] = {}
        # Individual instructions: (room, club) -> player id -> code.
        self._instructions: dict[tuple[str, str], dict[str, str]] = {}

    @staticmethod
    def _current_players(room_id: str, market: InitialMarket):
        # Runtime import avoids the service dependency cycle while keeping the
        # lineup evaluation identical to the current season's simulation inputs.
        from app.services.season_service import season_service
        season = season_service._seasons.get(room_id)
        if not season:
            return market.catalog
        return {player_id: player.model_copy(update={"overall": season.current_overalls.get(player_id, player.overall)})
                for player_id, player in market.catalog.items()}

    def squad(self, room_id: str, club_code: str) -> dict[str, object]:
        session = market_service._session(room_id)
        market = session.market
        if not market.selection_complete:
            raise MarketError("O elenco será liberado após a confirmação do mercado.")
        team = market.teams[club_code]
        players = self._current_players(room_id, market)
        lineup = self._lineups.get((room_id, club_code))
        if lineup:
            lineup = {**lineup, "evaluation": validate_lineup(mode=market.mode, formation_code=lineup["formation_code"], assignments=lineup["assignments"], roster=team.roster, players=players)}
        return {
            "club_code": club_code,
            "budget_cents": team.budget_cents,
            "players": [players[player_id].model_dump() for player_id in team.roster],
            "formations": formations(market.mode),
            "lineup": lineup,
            "strategy": self.strategy_for(room_id, club_code),
            "strategies": [{"code": code, "name": STRATEGY_NAMES[code], "effect": self._strategy_effect(code)} for code in LEGACY_STRATEGIES],
            "tactics": self.tactics_for(room_id, club_code).view(),
            "tactics_options": tactics_catalog(),
            "instructions": self.instructions_for(room_id, club_code),
            "instruction_options": instruction_catalog(),
            "cohesion": self._cohesion(room_id, market, club_code),
        }

    @staticmethod
    def _cohesion(room_id: str, market: InitialMarket, club_code: str) -> dict[str, object] | None:
        from app.services.season_service import season_service
        if room_id not in season_service._seasons:
            return None
        return season_service.cohesion_view(room_id, market, club_code)

    def save_instructions(self, room_id: str, club_code: str, instructions: dict[str, str]) -> dict[str, object]:
        """Validate per-player instructions against the slot each player occupies."""
        from app.services.season_service import INSTRUCTION_CODES, starter_roles
        session = market_service._session(room_id)
        market = session.market
        lineup = self._lineups.get((room_id, club_code))
        if not lineup:
            raise MarketError("Salve a escalação antes de definir instruções individuais.")
        slots = formation_slots(market.mode, str(lineup["formation_code"]))
        roles = starter_roles(slots)
        slot_of = {player_id: slot_id for slot_id, player_id in dict(lineup["assignments"]).items()}
        clean: dict[str, str] = {}
        for player_id, code in instructions.items():
            if player_id not in slot_of:
                raise MarketError("Instruções individuais valem apenas para titulares.")
            if code not in INSTRUCTION_CODES[roles[slot_of[player_id]]]:
                raise MarketError("Instrução individual inválida para a posição do atleta.")
            clean[player_id] = code
        self._instructions[(room_id, club_code)] = clean
        return {"instructions": clean}

    def instructions_for(self, room_id: str, club_code: str) -> dict[str, str]:
        return dict(self._instructions.get((room_id, club_code), {}))

    def set_instructions(self, room_id: str, club_code: str, instructions: dict[str, str]) -> None:
        """Server-side (bots): already validated by the caller."""
        self._instructions[(room_id, club_code)] = dict(instructions)

    def save_lineup(self, room_id: str, club_code: str, formation_code: str, assignments: dict[str, str]) -> dict[str, object]:
        session = market_service._session(room_id)
        market = session.market
        team = market.teams[club_code]
        evaluation = validate_lineup(mode=market.mode, formation_code=formation_code, assignments=assignments, roster=team.roster, players=self._current_players(room_id, market))
        lineup = {"formation_code": formation_code, "assignments": assignments, "evaluation": evaluation}
        self._lineups[(room_id, club_code)] = lineup
        return lineup

    def prepare_replacement(self, room_id: str, club_code: str, outgoing_id: str, incoming_id: str, market: InitialMarket) -> dict[str, object] | None:
        current = self._lineups.get((room_id, club_code))
        if current is None:
            return None
        team = market.teams[club_code]
        assignments = {slot: incoming_id if player_id == outgoing_id else player_id for slot, player_id in current["assignments"].items()}
        roster = [incoming_id if player_id == outgoing_id else player_id for player_id in team.roster]
        evaluation = validate_lineup(mode=market.mode, formation_code=current["formation_code"], assignments=assignments, roster=roster, players=self._current_players(room_id, market))
        return {"formation_code": current["formation_code"], "assignments": assignments, "evaluation": evaluation}

    def commit_lineup(self, room_id: str, club_code: str, lineup: dict[str, object]) -> None:
        self._lineups[(room_id, club_code)] = lineup

    def save_strategy(self, room_id: str, club_code: str, strategy: str) -> dict[str, str]:
        """Legacy preset: maps onto the three-part tactics used by the engine."""
        if strategy not in LEGACY_STRATEGIES:
            raise MarketError("Estratégia inválida.")
        self._strategies[(room_id, club_code)] = strategy
        self._tactics[(room_id, club_code)] = LEGACY_STRATEGIES[strategy]
        return {"strategy": strategy, "name": STRATEGY_NAMES[strategy], "effect": self._strategy_effect(strategy)}

    def save_tactics(self, room_id: str, club_code: str, payload: dict[str, str]) -> dict[str, object]:
        try:
            tactics = tactics_from_payload(payload)
        except ValueError as error:
            raise MarketError(str(error)) from error
        self._tactics[(room_id, club_code)] = tactics
        self._strategies[(room_id, club_code)] = next((code for code, preset in LEGACY_STRATEGIES.items() if preset == tactics), "CUSTOM")
        return {"tactics": tactics.view(), "strategy": self._strategies[(room_id, club_code)]}

    def strategy_for(self, room_id: str, club_code: str) -> str:
        return self._strategies.get((room_id, club_code), "BALANCED")

    def tactics_for(self, room_id: str, club_code: str) -> Tactics:
        return self._tactics.get((room_id, club_code), Tactics())

    def lineup_for(self, room_id: str, club_code: str) -> dict[str, object] | None:
        return self._lineups.get((room_id, club_code))

    def export_room(self, room_id: str) -> dict[str, object]:
        return {
            "lineups": {club: lineup for (saved_room, club), lineup in self._lineups.items() if saved_room == room_id},
            "strategies": {club: strategy for (saved_room, club), strategy in self._strategies.items() if saved_room == room_id},
            "tactics": {club: tactics.view() for (saved_room, club), tactics in self._tactics.items() if saved_room == room_id},
            "instructions": {club: dict(values) for (saved_room, club), values in self._instructions.items() if saved_room == room_id},
        }

    def restore_room(self, room_id: str, payload: dict[str, object]) -> None:
        lineups = payload.get("lineups", {})
        strategies = payload.get("strategies", {})
        if not isinstance(lineups, dict) or not isinstance(strategies, dict):
            raise ValueError("Snapshot de escalação inválido.")
        for club, lineup in lineups.items():
            if not isinstance(lineup, dict) or not isinstance(lineup.get("assignments"), dict):
                raise ValueError("Snapshot contém escalação inválida.")
            self._lineups[(room_id, str(club))] = lineup
        for club, strategy in strategies.items():
            if str(strategy) not in LEGACY_STRATEGIES and str(strategy) != "CUSTOM":
                raise ValueError("Snapshot contém estratégia inválida.")
            self._strategies[(room_id, str(club))] = str(strategy)
            if str(strategy) in LEGACY_STRATEGIES:
                self._tactics[(room_id, str(club))] = LEGACY_STRATEGIES[str(strategy)]
        tactics = payload.get("tactics", {})
        if not isinstance(tactics, dict):
            raise ValueError("Snapshot contém táticas inválidas.")
        for club, value in tactics.items():
            try:
                self._tactics[(room_id, str(club))] = tactics_from_payload(value)
            except ValueError as error:
                raise ValueError("Snapshot contém táticas inválidas.") from error
        instructions = payload.get("instructions", {})
        if not isinstance(instructions, dict):
            raise ValueError("Snapshot contém instruções inválidas.")
        for club, values in instructions.items():
            if isinstance(values, dict):
                self._instructions[(room_id, str(club))] = {str(k): str(v) for k, v in values.items()}

    @staticmethod
    def _strategy_effect(strategy: str) -> str:
        """Plain-language summary of each legacy preset (the engine uses tactics)."""
        return {
            "BALANCED": "Mantém o equilíbrio entre criação e proteção defensiva.",
            "ATTACKING": "Aumenta a frequência de ataques, com maior exposição atrás.",
            "DEFENSIVE": "Reduz chances concedidas, mas limita a produção ofensiva.",
            "COUNTER": "Explora espaços de equipes ofensivas e cede controle de bola.",
            "POSSESSION": "Melhora a circulação e exige bons passadores no meio.",
            "HIGH_PRESS": "Aumenta recuperações no campo rival e abre espaços defensivos.",
        }[strategy]


STRATEGY_NAMES = {
    "BALANCED": "Equilibrada", "ATTACKING": "Ofensiva", "DEFENSIVE": "Defensiva",
    "COUNTER": "Contra-ataque", "POSSESSION": "Posse de bola", "HIGH_PRESS": "Pressão alta",
}

squad_service = SquadService()
