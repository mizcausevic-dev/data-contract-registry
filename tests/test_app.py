"""End-to-end tests for the FastAPI app."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from data_contract_registry.app import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _contract(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dataset_id": "users.daily_active",
        "version": "1.0.0",
        "fields": [
            {"name": "user_id", "type": "string"},
            {"name": "active_date", "type": "timestamp"},
            {"name": "plan", "type": "string", "enum": ["free", "pro", "enterprise"]},
            {"name": "ltv", "type": "number", "required": False},
        ],
        "owners": [{"team": "growth-platform", "contact": "#growth-platform"}],
        "status": "active",
        "primary_key": ["user_id", "active_date"],
    }
    base.update(overrides)
    return base


class TestMeta:
    def test_root(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["name"] == "data-contract-registry"

    def test_healthz(self, client: TestClient) -> None:
        assert client.get("/healthz").json() == {"status": "ok"}


class TestRegistration:
    def test_first_register_returns_201_and_appears_in_datasets(self, client: TestClient) -> None:
        r = client.post("/contracts", json={"contract": _contract()})
        assert r.status_code == 201
        assert "users.daily_active" in client.get("/datasets").json()["datasets"]

    def test_compatible_minor_bump(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        body = _contract(
            version="1.1.0",
            fields=[
                *_contract()["fields"],
                {"name": "signup_source", "type": "string", "required": False},
            ],
        )
        r = client.post("/contracts", json={"contract": body})
        assert r.status_code == 201

    def test_incompatible_promotion_is_422(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        # Removing 'ltv' breaks backward compatibility.
        new_fields = [f for f in _contract()["fields"] if f["name"] != "ltv"]
        r = client.post("/contracts", json={"contract": _contract(version="2.0.0", fields=new_fields)})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["compatible"] is False
        assert any(i["kind"] == "field_removed" for i in detail["issues"])

    def test_duplicate_version_is_400(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        r = client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        assert r.status_code == 400


class TestRead:
    def test_latest_and_history(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        client.post(
            "/contracts",
            json={
                "contract": _contract(
                    version="1.1.0",
                    fields=[*_contract()["fields"], {"name": "x", "type": "string", "required": False}],
                )
            },
        )
        latest = client.get("/contracts/users.daily_active/latest").json()
        assert latest["version"] == "1.1.0"
        history = client.get("/contracts/users.daily_active/versions").json()
        assert [c["version"] for c in history] == ["1.0.0", "1.1.0"]

    def test_get_specific_version(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        r = client.get("/contracts/users.daily_active/versions/1.0.0")
        assert r.status_code == 200
        assert r.json()["version"] == "1.0.0"

    def test_unknown_dataset_404(self, client: TestClient) -> None:
        assert client.get("/contracts/nope/latest").status_code == 404


class TestDeprecateAndArchive:
    def test_deprecate(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract()})
        r = client.post(
            "/contracts/users.daily_active/versions/1.0.0/deprecate",
            json={"deprecation_uri": "https://wiki/migrate"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "deprecated"

    def test_archive(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract()})
        r = client.post("/contracts/users.daily_active/versions/1.0.0/archive")
        assert r.status_code == 200
        assert r.json()["status"] == "archived"


class TestDryRun:
    def test_check_does_not_register(self, client: TestClient) -> None:
        client.post("/contracts", json={"contract": _contract(version="1.0.0")})
        new_fields = [f for f in _contract()["fields"] if f["name"] != "ltv"]
        r = client.post(
            "/contracts/check",
            json={"contract": _contract(version="2.0.0", fields=new_fields)},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["compatible"] is False
        # Original registration is unchanged.
        history = client.get("/contracts/users.daily_active/versions").json()
        assert len(history) == 1


class TestBridge:
    def test_owners_from_decision_card(self, client: TestClient) -> None:
        card = {
            "decision_card_version": "0.1",
            "decision_id": "T-1",
            "issued_at": "2026-05-14T19:00:00Z",
            "buyer": {"name": "Springfield USD", "type": "school-district"},
            "decision_maker": {"role": "Director of Data", "name": "Alex Chen"},
            "decision": {"status": "approved"},
            "subject": {"vendor_name": "AcmeTutor"},
            "rationale": "Looks fine.",
        }
        r = client.post("/contracts/owners/from-decision-card", json=card)
        assert r.status_code == 200
        owners = r.json()
        assert owners[0]["team"] == "Springfield USD"
        assert "Director of Data" in owners[1]["team"]

    def test_owners_from_invalid_card_400(self, client: TestClient) -> None:
        r = client.post("/contracts/owners/from-decision-card", json={"no": "buyer"})
        assert r.status_code == 400


class TestAuditStreamWiring:
    """The three endpoints that emit governance events must do so when
    AUDIT_STREAM_URL is set, and stay silent when it isn't."""

    def _emit_capture(self, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, Any]]]:
        monkeypatch.setenv("AUDIT_STREAM_URL", "http://audit.local")
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(201, json={"event_id": len(captured)})

        c = TestClient(app)
        c.__enter__()
        app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return c, captured

    def test_register_emits_contract_promoted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c, captured = self._emit_capture(monkeypatch)
        try:
            r = c.post("/contracts", json={"contract": _contract()})
            assert r.status_code == 201
        finally:
            c.__exit__(None, None, None)
        assert any(e["kind"] == "contract_promoted" for e in captured)
        evt = next(e for e in captured if e["kind"] == "contract_promoted")
        assert evt["source"] == "data-contract-registry"
        assert evt["payload"]["dataset_id"] == "users.daily_active"
        assert evt["payload"]["version"] == "1.0.0"
        assert "growth-platform" in evt["payload"]["owners"]

    def test_incompatible_register_emits_compatibility_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c, captured = self._emit_capture(monkeypatch)
        try:
            # First, register a baseline.
            c.post("/contracts", json={"contract": _contract(version="1.0.0")})
            captured.clear()
            # Now try to ship a breaking change (drop a field).
            new_fields = [f for f in _contract()["fields"] if f["name"] != "ltv"]
            r = c.post(
                "/contracts",
                json={"contract": _contract(version="2.0.0", fields=new_fields)},
            )
            assert r.status_code == 422
        finally:
            c.__exit__(None, None, None)
        assert any(e["kind"] == "contract_compatibility_failed" for e in captured)
        evt = next(e for e in captured if e["kind"] == "contract_compatibility_failed")
        assert evt["payload"]["dataset_id"] == "users.daily_active"
        assert evt["payload"]["version"] == "2.0.0"
        assert evt["payload"]["issue_count"] >= 1

    def test_deprecate_emits_contract_deprecated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c, captured = self._emit_capture(monkeypatch)
        try:
            c.post("/contracts", json={"contract": _contract()})
            captured.clear()
            r = c.post(
                "/contracts/users.daily_active/versions/1.0.0/deprecate",
                json={"deprecation_uri": "https://wiki/migrate"},
            )
            assert r.status_code == 200
        finally:
            c.__exit__(None, None, None)
        assert any(e["kind"] == "contract_deprecated" for e in captured)
        evt = next(e for e in captured if e["kind"] == "contract_deprecated")
        assert evt["payload"]["deprecation_uri"] == "https://wiki/migrate"

    def test_no_emit_when_audit_stream_url_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUDIT_STREAM_URL", raising=False)
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(201)

        c = TestClient(app)
        c.__enter__()
        try:
            app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            r = c.post("/contracts", json={"contract": _contract()})
            assert r.status_code == 201
        finally:
            c.__exit__(None, None, None)
        assert captured == []
