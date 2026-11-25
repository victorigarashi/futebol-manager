"""Result ledger for engines that run on the coaches' machines (engine-neutral, Phase 5)."""

from __future__ import annotations

import pytest

from app.domain.external_results import ExternalResultError, ExternalResultLedger

SUM = "sha256:" + "a" * 64


def _ledger() -> ExternalResultLedger:
    ledger = ExternalResultLedger()
    ledger.open("r8-1", SUM, "COR", "SAO")
    return ledger


def test_two_matching_reports_confirm_and_the_table_receives_it_once():
    ledger = _ledger()
    assert ledger.report("r8-1", SUM, "COR", 2, 1, 1.0) == "PENDING"
    assert ledger.report("r8-1", SUM, "SAO", 2, 1, 2.0) == "CONFIRMED"
    assert ledger.take_confirmed("r8-1") == (2, 1)
    assert ledger.take_confirmed("r8-1") is None                   # a second commit writes nothing
    assert ledger.status("r8-1").status == "COMMITTED"


def test_repeated_report_is_idempotent_and_a_confirmed_result_never_changes():
    ledger = _ledger()
    ledger.report("r8-1", SUM, "COR", 1, 0, 1.0)
    assert ledger.report("r8-1", SUM, "COR", 1, 0, 1.5) == "PENDING"   # double click / retry
    ledger.report("r8-1", SUM, "SAO", 1, 0, 2.0)
    assert ledger.report("r8-1", SUM, "SAO", 1, 0, 3.0) == "CONFIRMED"
    with pytest.raises(ExternalResultError, match="já confirmado"):
        ledger.report("r8-1", SUM, "COR", 3, 0, 4.0)
    assert [a["outcome"] for a in ledger.status("r8-1").audit] == ["PENDING", "DUPLICATE", "CONFIRMED", "DUPLICATE", "REFUSED"]


def test_conflicting_reports_are_disputed_and_nothing_is_written():
    ledger = _ledger()
    ledger.report("r8-1", SUM, "COR", 2, 1, 1.0)
    assert ledger.report("r8-1", SUM, "SAO", 1, 1, 2.0) == "DISPUTED"
    assert ledger.take_confirmed("r8-1") is None
    with pytest.raises(ExternalResultError, match="outro placar"):
        ledger.report("r8-1", SUM, "COR", 1, 1, 3.0)


def test_reports_for_another_payload_or_from_outsiders_are_refused_and_audited():
    ledger = _ledger()
    with pytest.raises(ExternalResultError, match="outro contrato"):
        ledger.report("r8-1", "sha256:" + "b" * 64, "COR", 1, 0, 1.0)
    with pytest.raises(ExternalResultError, match="dois clubes"):
        ledger.report("r8-1", SUM, "PAL", 1, 0, 1.0)
    with pytest.raises(ExternalResultError, match="Placar"):
        ledger.report("r8-1", SUM, "COR", -1, 0, 1.0)
    with pytest.raises(ExternalResultError, match="não entregue"):
        ledger.report("other", SUM, "COR", 1, 0, 1.0)
    assert all(a["outcome"] == "REFUSED" for a in ledger.status("r8-1").audit)
    assert ledger.status("r8-1").status == "PENDING"


def test_opening_twice_is_idempotent_but_not_with_another_payload():
    ledger = _ledger()
    assert ledger.open("r8-1", SUM, "COR", "SAO") is ledger.status("r8-1")
    with pytest.raises(ExternalResultError, match="outro contrato"):
        ledger.open("r8-1", "sha256:" + "c" * 64, "COR", "SAO")
    with pytest.raises(ExternalResultError, match="checksum"):
        ExternalResultLedger().open("x", "", "COR", "SAO")
