"""In-memory squad lineups, kept separate from the market rules."""

from __future__ import annotations

from app.domain.market import InitialMarket, MarketError
from app.domain.simulation import STRATEGIES
from app.domain.squad import formations, validate_lineup
from app.services.market_service import market_service


class SquadService:
    def __init__(self) -> None:
        self._lineups: dict[tuple[str, str], dict[str, object]] = {}
        self._strategies: dict[tuple[str, str], str] = {}

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
            "strategies": [{"code": code, "name": name, "effect": self._strategy_effect(code)} for code, name in STRATEGIES.items()],
        }

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
        if strategy not in STRATEGIES:
            raise MarketError("Estratégia inválida.")
        self._strategies[(room_id, club_code)] = strategy
        return {"strategy": strategy, "name": STRATEGIES[strategy], "effect": self._strategy_effect(strategy)}

    def strategy_for(self, room_id: str, club_code: str) -> str:
        return self._strategies.get((room_id, club_code), "BALANCED")

    def lineup_for(self, room_id: str, club_code: str) -> dict[str, object] | None:
        return self._lineups.get((room_id, club_code))

    def export_room(self, room_id: str) -> dict[str, object]:
        return {
            "lineups": {club: lineup for (saved_room, club), lineup in self._lineups.items() if saved_room == room_id},
            "strategies": {club: strategy for (saved_room, club), strategy in self._strategies.items() if saved_room == room_id},
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
            if str(strategy) not in STRATEGIES:
                raise ValueError("Snapshot contém estratégia inválida.")
            self._strategies[(room_id, str(club))] = str(strategy)

    @staticmethod
    def _strategy_effect(strategy: str) -> str:
        return {
            "BALANCED": "Mantém o equilíbrio entre criação e proteção defensiva.",
            "ATTACKING": "Aumenta a frequência de ataques, com maior exposição atrás.",
            "DEFENSIVE": "Reduz chances concedidas, mas limita a produção ofensiva.",
            "COUNTER": "Explora espaços de equipes ofensivas e cede controle de bola.",
            "POSSESSION": "Melhora a circulação e exige bons passadores no meio.",
            "HIGH_PRESS": "Aumenta recuperações no campo rival e abre espaços defensivos.",
        }[strategy]


squad_service = SquadService()
