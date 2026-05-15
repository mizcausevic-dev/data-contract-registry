"""Tests for the Decision Card -> Owner list bridge."""

from __future__ import annotations

import pytest

from data_contract_registry.from_decision_card import contract_owner_from_decision_card


def _card() -> dict[str, object]:
    return {
        "decision_card_version": "0.1",
        "decision_id": "TEST-001",
        "issued_at": "2026-05-14T19:00:00Z",
        "buyer": {"name": "Springfield USD", "type": "school-district", "contact": "#data-platform"},
        "decision_maker": {"role": "Director of Data", "name": "Alex Chen"},
        "decision": {"status": "approved"},
        "subject": {"vendor_name": "AcmeTutor"},
        "rationale": "Looks fine.",
    }


class TestOwnersFromDecisionCard:
    def test_buyer_becomes_primary_owner(self) -> None:
        owners = contract_owner_from_decision_card(_card())
        assert owners[0].team == "Springfield USD"
        assert owners[0].contact == "#data-platform"

    def test_decision_maker_role_becomes_secondary_owner(self) -> None:
        owners = contract_owner_from_decision_card(_card())
        assert len(owners) == 2
        assert "Director of Data" in owners[1].team
        assert "Alex Chen" in owners[1].team

    def test_no_decision_maker_yields_only_buyer(self) -> None:
        card = _card()
        del card["decision_maker"]
        owners = contract_owner_from_decision_card(card)
        assert len(owners) == 1
        assert owners[0].team == "Springfield USD"

    def test_missing_buyer_raises(self) -> None:
        card = _card()
        del card["buyer"]
        with pytest.raises(ValueError, match="buyer"):
            contract_owner_from_decision_card(card)

    def test_missing_buyer_name_raises(self) -> None:
        card = _card()
        card["buyer"] = {"type": "school-district"}
        with pytest.raises(ValueError, match=r"buyer\.name"):
            contract_owner_from_decision_card(card)
