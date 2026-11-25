"""Match engine adapters: one interface, capabilities that reflect tests, not expectations.

`CurrentEngineAdapter` describes the engine the game uses today (Resenha: server-authoritative
`HighlightMatch` for coached matches, `MatchEngine` for simulated ones). It does not change how
matches are played; the season keeps calling its engines directly. Its capabilities are the ones
the existing test suites and multiplayer verifications prove.

`Pes2013Adapter` is a capability-based placeholder for an external PES 2013 Web runtime. Nothing
about that runtime has been validated in this repository (how it loads rosters, whether teams
can be selected or a match started programmatically, how a result could be read, whether its
network layer supports a real two-machine match). Every capability is therefore False and every
operation fails explicitly. It is only reachable when the `pes2013_adapter_enabled` flag is on.

No external engine code, binaries or assets are part of this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from app.domain.match_contract import MatchPayload, verify_checksum


@dataclass(frozen=True)
class EngineCapabilities:
    can_load_custom_roster: bool
    can_select_teams: bool
    can_auto_start_match: bool
    can_read_result: bool
    can_netplay: bool
    supports_5v5: bool
    supports_11v11: bool
    # Where each True comes from (tests / verification), or why each False is False.
    evidence: tuple[str, ...] = ()

    def view(self) -> dict[str, object]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


class EngineCapabilityError(RuntimeError):
    """The engine cannot do what was asked (not supported, not validated, or disabled)."""


@dataclass(frozen=True)
class PreparedMatch:
    engine: str
    match_id: str
    payload_checksum: str


class MatchEngineAdapter(Protocol):
    name: str
    status: str            # "AVAILABLE" | "EXPERIMENTAL_UNAVAILABLE" | "DISABLED"

    def capabilities(self) -> EngineCapabilities: ...

    def prepare(self, payload: MatchPayload) -> PreparedMatch: ...


def _check(payload: MatchPayload, caps: EngineCapabilities, engine: str) -> None:
    if not verify_checksum(payload):
        raise EngineCapabilityError("Contrato de partida adulterado ou sem checksum.")
    supported = caps.supports_5v5 if payload.mode == "FIVE_A_SIDE" else caps.supports_11v11
    if not supported:
        raise EngineCapabilityError(f"{engine} não suporta o modo {payload.mode}.")


class CurrentEngineAdapter:
    name = "RESENHA"
    status = "AVAILABLE"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            can_load_custom_roster=True, can_select_teams=True, can_auto_start_match=True, can_read_result=True,
            can_netplay=True, supports_5v5=True, supports_11v11=True,
            evidence=(
                "Elencos e escalações do Resenha: SeasonService._team_input (testes de temporada e competição).",
                "Partida iniciada pelo servidor ao abrir a rodada: SeasonService.advance.",
                "Resultado oficial gravado uma vez por rodada: SeasonService.finish_due / highlight_record.",
                "Multiplayer autoritativo no servidor entre dois navegadores (2D/3D): test_football_v8_sync.py, "
                "frontend/scripts/verify-match-full.cjs.",
            ))

    def prepare(self, payload: MatchPayload) -> PreparedMatch:
        _check(payload, self.capabilities(), self.name)
        return PreparedMatch(self.name, payload.match_id, payload.checksum)


class Pes2013Adapter:
    name = "PES2013_WEB"
    status = "EXPERIMENTAL_UNAVAILABLE"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            can_load_custom_roster=False, can_select_teams=False, can_auto_start_match=False, can_read_result=False,
            can_netplay=False, supports_5v5=False, supports_11v11=False,
            evidence=(
                "Nenhum artefato do runtime (manifest, worker, documentação) disponível neste repositório.",
                "Carga de elenco (ex.: EDIT.bin) não demonstrada; formato e ponto de leitura desconhecidos.",
                "Seleção de times, início automático e leitura de resultado: nenhuma API conhecida.",
                "Rede: ponte WebSocket restrita a localhost observada em análise anterior; partida em dois PCs não testada.",
                "Modo 5x5 não existe no PES 2013 até prova em contrário.",
            ))

    def prepare(self, payload: MatchPayload) -> PreparedMatch:
        raise EngineCapabilityError("PES 2013 Web: integração experimental, ainda não validada. Jogue com a engine atual.")


ADAPTERS: dict[str, type] = {CurrentEngineAdapter.name: CurrentEngineAdapter, Pes2013Adapter.name: Pes2013Adapter}


def engine_adapter(name: str, *, pes2013_enabled: bool) -> MatchEngineAdapter:
    if name not in ADAPTERS:
        raise EngineCapabilityError(f"Engine desconhecida: {name}.")
    if name == Pes2013Adapter.name and not pes2013_enabled:
        raise EngineCapabilityError("PES 2013 Web desativado (feature flag PES2013_ADAPTER_ENABLED).")
    return ADAPTERS[name]()


def engines_view(*, pes2013_enabled: bool) -> list[dict[str, object]]:
    """What the UI shows: every engine, its status and the tested capability matrix."""
    out = []
    for cls in ADAPTERS.values():
        adapter = cls()
        status = adapter.status if (cls is not Pes2013Adapter or pes2013_enabled) else "DISABLED"
        out.append({"name": adapter.name, "status": status, "capabilities": adapter.capabilities().view()})
    return out
