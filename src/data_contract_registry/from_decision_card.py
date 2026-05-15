"""
Bridge to AI Procurement Decision Cards.

When a buyer approves a vendor whose data product the team will consume, the
Decision Card's `buyer.name` + `decision_maker` are *the right answers* to
"who owns the contract on our side". This helper extracts those fields into
`Owner` records so a freshly registered contract carries them automatically
instead of asking the data team to re-type them.

Tiny, but it's the third cross-ecosystem hook in the portfolio.
"""

from __future__ import annotations

from typing import Any

from .models import Owner


def contract_owner_from_decision_card(card: dict[str, Any]) -> list[Owner]:
    """
    Pull a credible owner list out of a Kinetic Gain Procurement Decision Card.

    The buyer's team is always owner #0. If the card also declares a
    `decision_maker.role` we add that as a secondary owner so on-call routing
    has a name to page.
    """
    if "buyer" not in card or not isinstance(card["buyer"], dict):
        raise ValueError("Decision Card is missing required 'buyer' object")
    buyer = card["buyer"]
    name = buyer.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("buyer.name is required and must be a non-empty string")

    owners: list[Owner] = [Owner(team=name, contact=buyer.get("contact") or None)]

    decision_maker = card.get("decision_maker") or {}
    if isinstance(decision_maker, dict):
        role = decision_maker.get("role")
        dm_name = decision_maker.get("name")
        if role:
            owners.append(
                Owner(
                    team=f"{role}" + (f" ({dm_name})" if dm_name else ""),
                    contact=decision_maker.get("authority") or None,
                )
            )

    return owners
