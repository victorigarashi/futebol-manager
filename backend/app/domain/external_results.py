"""Results reported by an engine that runs on the coaches' machines (Phase 5, engine-neutral).

The current Resenha engine is server-authoritative: the server computes the result and nobody
reports anything. An external engine running in the browsers (e.g. a PES 2013 Web runtime) would
only be known to the server through the clients. This ledger is the rule for accepting such a
result, before anything touches the official table:

- A report names the match AND the checksum of the MatchPayload it was played from. A report
  for another payload (other line-ups, other seed, tampered data) is refused.
- Only the two participating clubs can report, and each one only for itself.
- The result is CONFIRMED only when both coaches report the same score; until then PENDING.
  A bot side cannot report: a match against a bot needs a server-side engine.
- Different scores: DISPUTED. Nothing is written; the dispute is kept for review.
- Sending the same report again is a no-op (idempotency key = club + match + checksum + score);
  a CONFIRMED result never changes and is handed to the season exactly once (`take_confirmed`).
- Every report (accepted or refused) is in the audit trail, without secrets.

Limit, stated plainly: two coaches who agree to lie produce a CONFIRMED false result. Agreement
proves consistency between the two clients, not the truth of the match. Only an engine whose
result the server can verify (or compute) removes that limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class ExternalResultError(ValueError):
    """The report is refused (the message says why, in Portuguese)."""


@dataclass(frozen=True)
class ResultReport:
    club_code: str
    home_goals: int
    away_goals: int

    def score(self) -> tuple[int, int]:
        return self.home_goals, self.away_goals


@dataclass
class ExternalMatch:
    match_id: str
    payload_checksum: str
    home: str
    away: str
    reports: dict[str, ResultReport] = field(default_factory=dict)
    status: str = "PENDING"            # PENDING | CONFIRMED | DISPUTED | COMMITTED
    audit: list[dict[str, object]] = field(default_factory=list)


class ExternalResultLedger:
    def __init__(self) -> None:
        self._matches: dict[str, ExternalMatch] = {}

    def open(self, match_id: str, payload_checksum: str, home: str, away: str) -> ExternalMatch:
        """Register a match handed to an external engine (idempotent for the same payload)."""
        current = self._matches.get(match_id)
        if current is not None:
            if current.payload_checksum != payload_checksum:
                raise ExternalResultError("Partida já entregue a uma engine com outro contrato.")
            return current
        if not payload_checksum.startswith("sha256:"):
            raise ExternalResultError("Contrato de partida sem checksum.")
        match = ExternalMatch(match_id, payload_checksum, home, away)
        self._matches[match_id] = match
        return match

    def status(self, match_id: str) -> ExternalMatch:
        if match_id not in self._matches:
            raise ExternalResultError("Partida não entregue a uma engine externa.")
        return self._matches[match_id]

    def report(self, match_id: str, payload_checksum: str, club_code: str, home_goals: int, away_goals: int, at: float) -> str:
        match = self.status(match_id)
        entry = {"at": at, "club": club_code, "score": [home_goals, away_goals], "checksum_ok": payload_checksum == match.payload_checksum}

        def refuse(reason: str) -> None:
            match.audit.append({**entry, "outcome": "REFUSED", "reason": reason})
            raise ExternalResultError(reason)

        if payload_checksum != match.payload_checksum:
            refuse("Resultado de outro contrato de partida (escalação, semente ou dados diferentes).")
        if club_code not in (match.home, match.away):
            refuse("Só os dois clubes da partida podem informar o resultado.")
        if not (0 <= home_goals <= 99 and 0 <= away_goals <= 99):
            refuse("Placar inválido.")
        report = ResultReport(club_code, int(home_goals), int(away_goals))
        previous = match.reports.get(club_code)
        if previous == report:
            match.audit.append({**entry, "outcome": "DUPLICATE"})
            return match.status
        if match.status in ("CONFIRMED", "COMMITTED"):
            refuse("Resultado já confirmado: não pode ser alterado.")
        if previous is not None:
            refuse("Este clube já informou outro placar; a divergência fica registrada para revisão.")
        match.reports[club_code] = report
        reports = list(match.reports.values())
        if len(reports) == 2:
            match.status = "CONFIRMED" if reports[0].score() == reports[1].score() else "DISPUTED"
        match.audit.append({**entry, "outcome": match.status})
        return match.status

    def take_confirmed(self, match_id: str) -> tuple[int, int] | None:
        """The confirmed score, exactly once (the season writes it to the table); then COMMITTED."""
        match = self.status(match_id)
        if match.status != "CONFIRMED":
            return None
        match.status = "COMMITTED"
        match.audit.append({"outcome": "COMMITTED"})
        return next(iter(match.reports.values())).score()
