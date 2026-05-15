"""Unit tests for the compatibility checker."""

from __future__ import annotations

import pytest

from data_contract_registry.compatibility import CompatibilityChecker
from data_contract_registry.models import DataField

from .conftest import make_contract


class TestVersionAndStructural:
    def test_compatible_identical_minus_minor_bump(self) -> None:
        prev = make_contract()
        new = make_contract(version="1.1.0")
        report = CompatibilityChecker().check(prev, new)
        assert report.compatible
        assert not report.errors

    def test_version_must_strictly_increase(self) -> None:
        prev = make_contract(version="1.0.0")
        same = make_contract(version="1.0.0")
        report = CompatibilityChecker().check(prev, same)
        assert not report.compatible
        assert any(i.kind == "version_not_increasing" for i in report.errors)

    def test_primary_key_change_is_breaking(self) -> None:
        prev = make_contract(version="1.0.0", primary_key=["user_id", "active_date"])
        new = make_contract(version="2.0.0", primary_key=["user_id"])
        report = CompatibilityChecker().check(prev, new)
        assert any(i.kind == "primary_key_changed" for i in report.errors)


class TestBackwardCompatibility:
    def test_removing_a_field_breaks_backward(self) -> None:
        prev = make_contract(version="1.0.0")
        fields = [f for f in prev.fields if f.name != "ltv"]
        new = make_contract(version="2.0.0", fields=fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert not report.compatible
        assert any(i.kind == "field_removed" for i in report.errors)

    def test_changing_a_field_type_breaks_backward(self) -> None:
        prev = make_contract(version="1.0.0")
        fields = [
            DataField(name=f.name, type="integer" if f.name == "user_id" else f.type, required=f.required)
            for f in prev.fields
        ]
        new = make_contract(version="2.0.0", fields=fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert any(i.kind == "field_type_changed" for i in report.errors)

    def test_promoting_optional_to_required_breaks_backward(self) -> None:
        prev = make_contract(version="1.0.0")  # ltv is required=False
        fields = []
        for f in prev.fields:
            if f.name == "ltv":
                fields.append(DataField(name=f.name, type=f.type, required=True))
            else:
                fields.append(f)
        new = make_contract(version="2.0.0", fields=fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert any(i.kind == "field_required_added" for i in report.errors)

    def test_shrinking_an_enum_breaks_backward(self) -> None:
        prev = make_contract(version="1.0.0")
        new_fields = []
        for f in prev.fields:
            if f.name == "plan":
                new_fields.append(DataField(name=f.name, type=f.type, enum=["free", "pro"]))
            else:
                new_fields.append(f)
        new = make_contract(version="1.1.0", fields=new_fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert any(i.kind == "field_enum_shrunk" for i in report.errors)

    def test_adding_optional_field_is_backward_compatible(self) -> None:
        prev = make_contract(version="1.0.0")
        new_fields = [*list(prev.fields), DataField(name="referral_code", type="string", required=False)]
        new = make_contract(version="1.1.0", fields=new_fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert report.compatible

    def test_expanding_an_enum_is_backward_compatible(self) -> None:
        prev = make_contract(version="1.0.0")
        new_fields = []
        for f in prev.fields:
            if f.name == "plan":
                new_fields.append(
                    DataField(name=f.name, type=f.type, enum=["free", "pro", "enterprise", "team"])
                )
            else:
                new_fields.append(f)
        new = make_contract(version="1.1.0", fields=new_fields)
        report = CompatibilityChecker().check(prev, new, mode="backward")
        assert report.compatible


class TestForwardCompatibility:
    def test_adding_required_field_breaks_forward(self) -> None:
        prev = make_contract(version="1.0.0")
        new_fields = [*list(prev.fields), DataField(name="must_have", type="string", required=True)]
        new = make_contract(version="2.0.0", fields=new_fields)
        report = CompatibilityChecker().check(prev, new, mode="forward")
        assert any(i.kind == "field_required_added" for i in report.errors)

    def test_adding_optional_field_is_forward_compatible(self) -> None:
        prev = make_contract(version="1.0.0")
        new_fields = [*list(prev.fields), DataField(name="nice_to_have", type="string", required=False)]
        new = make_contract(version="1.1.0", fields=new_fields)
        report = CompatibilityChecker().check(prev, new, mode="forward")
        assert report.compatible


class TestFullAndNoneModes:
    def test_full_combines_backward_and_forward(self) -> None:
        prev = make_contract(version="1.0.0")
        # Both removed AND added required: should break in both directions.
        fields = [f for f in prev.fields if f.name != "ltv"]
        fields.append(DataField(name="new_required", type="string", required=True))
        new = make_contract(version="2.0.0", fields=fields)
        report = CompatibilityChecker().check(prev, new, mode="full")
        kinds = {i.kind for i in report.errors}
        assert "field_removed" in kinds
        assert "field_required_added" in kinds


class TestDatasetIdMismatch:
    def test_raises_when_dataset_ids_differ(self) -> None:
        prev = make_contract()
        new = make_contract(dataset_id="users.something_else", version="2.0.0")
        with pytest.raises(ValueError, match="dataset_id mismatch"):
            CompatibilityChecker().check(prev, new)
