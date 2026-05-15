"""Shared test fixtures."""

from __future__ import annotations

from data_contract_registry.models import DataContract, DataField, Owner


def make_contract(**overrides: object) -> DataContract:
    defaults: dict[str, object] = {
        "dataset_id": "users.daily_active",
        "version": "1.0.0",
        "description": "Daily active users.",
        "fields": [
            DataField(name="user_id", type="string"),
            DataField(name="active_date", type="timestamp"),
            DataField(name="plan", type="string", enum=["free", "pro", "enterprise"]),
            DataField(name="ltv", type="number", required=False),
        ],
        "owners": [Owner(team="growth-platform", contact="#growth-platform")],
        "status": "active",
        "primary_key": ["user_id", "active_date"],
    }
    defaults.update(overrides)
    return DataContract(**defaults)  # type: ignore[arg-type]
