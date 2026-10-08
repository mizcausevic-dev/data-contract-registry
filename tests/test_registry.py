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

    def test_unknown_mode_cannot_bypass_first_registration_or_dry_run(self) -> None:
        r = ContractRegistry()
        contract = make_contract()
        with pytest.raises(ValueError, match="unknown compatibility mode"):
            r.register(contract, compatibility="typo")  # type: ignore[arg-type]
        assert r.datasets() == []
        with pytest.raises(ValueError, match="unknown compatibility mode"):
            r.check(contract, compatibility="typo")  # type: ignore[arg-type]


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

    def test_archived_latest_still_sets_version_floor_and_matches_dry_run(self) -> None:
        r = ContractRegistry()
        r.register(make_contract(version="1.0.0"))
        r.register(make_contract(version="1.1.0"))
        r.archive("users.daily_active", "1.1.0")
        proposed = make_contract(version="1.0.5")

        dry_run = r.check(proposed)
        actual = r.register(proposed)
        assert not dry_run.compatible
        assert dry_run == actual
        assert any(i.kind == "version_not_increasing" for i in actual.errors)
        assert [c.version for c in r.history("users.daily_active")] == ["1.0.0", "1.1.0"]

    def test_caller_cannot_mutate_registered_history(self) -> None:
        r = ContractRegistry()
        original = make_contract()
        r.register(original)
        original.fields[0].name = "tampered_input"
        from_get = r.get("users.daily_active", "1.0.0")
        from_get.fields[0].name = "tampered_get"
        from_history = r.history("users.daily_active")
        from_history[0].owners[0].team = "tampered_history"
        from_latest = r.latest("users.daily_active")
        from_latest.primary_key.append("ltv")

        stored = r.get("users.daily_active", "1.0.0")
        assert stored.fields[0].name == "user_id"
        assert stored.owners[0].team == "growth-platform"
        assert stored.primary_key == ["user_id", "active_date"]


class TestDeprecateAndArchive:
    def test_deprecate_marks_status_and_uri(self) -> None:
        r = ContractRegistry()
        r.register(make_contract())
        updated = r.deprecate("users.daily_active", "1.0.0", deprecation_uri="https://wiki/x")
        assert updated.status == "deprecated"
        assert updated.deprecation_uri == "https://wiki/x"

    def test_rejects_blank_deprecation_uri_and_archived_revival(self) -> None:
        r = ContractRegistry()
        r.register(make_contract())
        with pytest.raises(ValueError, match="deprecation_uri"):
            r.deprecate("users.daily_active", "1.0.0", deprecation_uri="  ")
        r.archive("users.daily_active", "1.0.0")
        with pytest.raises(ValueError, match="archived"):
            r.deprecate("users.daily_active", "1.0.0", deprecation_uri="https://wiki/x")
        assert r.get("users.daily_active", "1.0.0").status == "archived"

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
