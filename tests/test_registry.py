"""Unit tests for the in-memory registry."""

from __future__ import annotations

import pytest

from data_contract_registry.models import DataField
from data_contract_registry.registry import ContractRegistry, RegistryError

from .conftest import make_contract


class TestFirstRegistration:
    def test_initial_contract_always_compatible(self) -> None:
        r = ContractRegistry()
        report = r.register(make_contract())
        assert report.compatible
        assert "users.daily_active" in r

    def test_unknown_dataset_lookups_raise(self) -> None:
        r = ContractRegistry()
        with pytest.raises(RegistryError):
            r.latest("nope")
        with pytest.raises(RegistryError):
            r.history("nope")
        with pytest.raises(RegistryError):
            r.get("nope", "1.0.0")


class TestPromotion:
    def test_compatible_promotion_succeeds(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))
        new_fields = [f for f in make_contract().fields] + [
            DataField(name="signup_source", type="string", required=False)
        ]
        report = r.register(make_contract(version="1.1.0", fields=new_fields))
        assert report.compatible
        assert r.latest("users.daily_active").version == "1.1.0"

    def test_incompatible_promotion_is_rejected_and_history_unchanged(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))

        new_fields = [f for f in make_contract().fields if f.name != "ltv"]
        report = r.register(make_contract(version="2.0.0", fields=new_fields))
        assert not report.compatible
        # History should not have grown.
        assert [c.version for c in r.history("users.daily_active")] == ["1.0.0"]

    def test_duplicate_version_raises(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))
        with pytest.raises(RegistryError, match="already registered"):
            r.register(make_contract(version="1.0.0"))


class TestDeprecateAndArchive:
    def test_deprecate_marks_status_and_uri(self) -> None:
        r = ContractRegistry()
        r.register(make_contract())
        updated = r.deprecate("users.daily_active", "1.0.0", deprecation_uri="https://wiki/x")
        assert updated.status == "deprecated"
        assert updated.deprecation_uri == "https://wiki/x"

    def test_archive_marks_status(self) -> None:
        r = ContractRegistry()
        r.register(make_contract())
        updated = r.archive("users.daily_active", "1.0.0")
        assert updated.status == "archived"

    def test_deprecate_unknown_dataset_raises(self) -> None:
        r = ContractRegistry()
        with pytest.raises(RegistryError):
            r.deprecate("nope", "1.0.0", deprecation_uri="x")

    def test_latest_returns_most_recent_active(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))
        new_fields = [*list(make_contract().fields), DataField(name="x", type="string", required=False)]
        r.register(make_contract(version="1.1.0", fields=new_fields))
        r.archive("users.daily_active", "1.1.0")
        assert r.latest("users.daily_active").version == "1.0.0"


class TestDryRun:
    def test_check_does_not_mutate(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))
        new_fields = [f for f in make_contract().fields if f.name != "ltv"]
        report = r.check(make_contract(version="2.0.0", fields=new_fields))
        assert not report.compatible
        assert [c.version for c in r.history("users.daily_active")] == ["1.0.0"]
