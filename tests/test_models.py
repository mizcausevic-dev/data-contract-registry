"""Unit tests for the Pydantic models."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from data_contract_registry import __version__
from data_contract_registry.models import DataContract, DataField, Owner

from .conftest import make_contract


class TestDataContract:
    def test_package_version_matches_project_metadata(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert __version__ == metadata["project"]["version"]

    def test_minimal_valid(self) -> None:
        c = make_contract()
        assert c.dataset_id == "users.daily_active"
        assert c.field("user_id") is not None

    def test_rejects_non_semver_version(self) -> None:
        with pytest.raises(ValidationError):
            make_contract(version="1")
        with pytest.raises(ValidationError):
            make_contract(version="v1.0.0")
        with pytest.raises(ValidationError):
            make_contract(version="01.0.0")
        with pytest.raises(ValidationError):
            make_contract(version="\u0661.0.0")

    def test_blank_identity_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DataField(name="  ", type="string")
        with pytest.raises(ValidationError):
            Owner(team="  ")
        with pytest.raises(ValidationError):
            Owner(team="team", contact="  ")
        with pytest.raises(ValidationError):
            make_contract(dataset_id="  ")

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

    def test_rejects_duplicate_or_optional_primary_key(self) -> None:
        with pytest.raises(ValidationError, match="primary_key fields must be unique"):
            make_contract(primary_key=["user_id", "user_id"])
        with pytest.raises(ValidationError, match="must be required"):
            make_contract(primary_key=["ltv"])

    @pytest.mark.parametrize(
        ("kind", "values"),
        [
            ("integer", [True]),
            ("boolean", [1]),
            ("string", [1]),
            ("timestamp", ["2026-01-01T00:00:00Z"]),
            ("number", []),
            ("number", [float("nan")]),
            ("number", [1, 1.0]),
        ],
    )
    def test_rejects_invalid_enum(self, kind: str, values: list[object]) -> None:
        with pytest.raises(ValidationError):
            DataField.model_validate({"name": "x", "type": kind, "enum": values})

    def test_accepts_fractional_number_enum(self) -> None:
        field = DataField(name="price", type="number", enum=[1.25, 2.5])
        assert field.enum == [1.25, 2.5]

    def test_exported_json_fixture_matches_yaml_contract(self) -> None:
        example_dir = Path(__file__).resolve().parents[1] / "examples"
        from_yaml = DataContract.model_validate(
            yaml.safe_load((example_dir / "contract.yaml").read_text(encoding="utf-8"))
        )
        from_json = json.loads((example_dir / "contract.json").read_text(encoding="utf-8"))
        assert DataContract.model_validate(from_json).model_dump(mode="json") == from_json
        assert from_yaml.model_dump(mode="json") == from_json

    def test_fractional_number_enum_fixture_round_trips(self) -> None:
        path = Path(__file__).resolve().parents[1] / "examples" / "contract-number-enum.json"
        from_json = json.loads(path.read_text(encoding="utf-8"))
        contract = DataContract.model_validate(from_json)
        assert contract.model_dump(mode="json") == from_json
        ltv = contract.field("ltv")
        assert ltv is not None
        assert ltv.enum == [1.25, 2.5]

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
