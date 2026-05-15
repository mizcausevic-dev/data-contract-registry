"""Unit tests for the Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_contract_registry.models import DataContract, DataField, Owner

from .conftest import make_contract


class TestDataContract:
    def test_minimal_valid(self) -> None:
        c = make_contract()
        assert c.dataset_id == "users.daily_active"
        assert c.field("user_id") is not None

    def test_rejects_non_semver_version(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(version="1")
        with pytest.raises(ValidationError):
            make_contract(version="v1.0.0")

    def test_rejects_duplicate_field_names(self) -> None:
        fields = [
            DataField(name="x", type="string"),
            DataField(name="x", type="integer"),
        ]
        with pytest.raises(ValidationError):
            DataContract(
                dataset_id="d",
                version="1.0.0",
                fields=fields,
                owners=[Owner(team="t")],
            )

    def test_rejects_primary_key_pointing_at_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            DataContract(
                dataset_id="d",
                version="1.0.0",
                fields=[DataField(name="a", type="string")],
                owners=[Owner(team="t")],
                primary_key=["b"],
            )

    def test_deprecated_requires_uri(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(status="deprecated")

    def test_strict_mode_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            DataContract.model_validate(
                {
                    "dataset_id": "d",
                    "version": "1.0.0",
                    "fields": [{"name": "x", "type": "string"}],
                    "owners": [{"team": "t"}],
                    "unknown_field": True,
                }
            )

    def test_field_lookup_returns_none_for_missing(self) -> None:
        c = make_contract()
        assert c.field("does-not-exist") is None
