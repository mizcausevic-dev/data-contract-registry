"""
Bridge to AI Procurement Decision Cards.

This helper maps a Decision Card's `buyer.name` and optional
`decision_maker.role` to candidate `Owner` records. A data steward must confirm
the contract owner and contact before registration. This function does not
validate the Decision Card, its status or signature, or anyone's authority.

Tiny, but it's the third cross-ecosystem hook in the portfolio.
"""

from __future__ import annotations

from typing import Any

from .models import Owner


def contract_owner_from_decision_card(card: dict[str, Any]) -> list[Owner]:
    """
    Suggest owners from buyer and decision-maker fields in a Decision Card.

    The buyer's organization is candidate #0. A decision-maker role, when
    present, is candidate #1. `decision_maker.authority` is an approval
    authority description, not a paging contact, so it is not mapped.
    """
    if "buyer" not in card or not isinstance(card["buyer"], dict):
        raise ValueError("Decision Card is missing required 'buyer' object")
    buyer = card["buyer"]
    name = buyer.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("buyer.name is required and must be a non-empty string")

    contact = buyer.get("contact")
    if contact is not None and not isinstance(contact, str):
        raise ValueError("buyer.contact must be a string when provided")
    normalized_contact = contact.strip() if contact else None
    owners: list[Owner] = [Owner(team=name.strip(), contact=normalized_contact or None)]

    decision_maker = card.get("decision_maker")
    if decision_maker is not None and not isinstance(decision_maker, dict):
        raise ValueError("decision_maker must be an object when provided")
    if isinstance(decision_maker, dict):
        role = decision_maker.get("role")
        dm_name = decision_maker.get("name")
        if role is not None and (not isinstance(role, str) or not role.strip()):
            raise ValueError("decision_maker.role must be a non-empty string when provided")
        if dm_name is not None and not isinstance(dm_name, str):
            raise ValueError("decision_maker.name must be a string when provided")
        if role:
            owners.append(
                Owner(team=role.strip() + (f" ({dm_name.strip()})" if dm_name and dm_name.strip() else ""))
            )

    return owners
