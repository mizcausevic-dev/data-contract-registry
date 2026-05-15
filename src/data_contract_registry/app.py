"""
FastAPI app — eight endpoints around the in-memory registry.

  GET  /                               service info
  GET  /healthz                        liveness probe
  GET  /datasets                       list registered dataset IDs
  POST /contracts                      register / promote a contract
  POST /contracts/check                dry-run compatibility check
  GET  /contracts/{ds}/latest          latest ACTIVE contract for a dataset
  GET  /contracts/{ds}/versions        full history
  GET  /contracts/{ds}/versions/{v}    fetch a specific version
  POST /contracts/{ds}/versions/{v}/deprecate
  POST /contracts/{ds}/versions/{v}/archive
  POST /contracts/owners/from-decision-card  cross-ecosystem hook
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ValidationError

from . import __version__, audit_stream
from .compatibility import CompatibilityMode
from .from_decision_card import contract_owner_from_decision_card
from .models import CompatibilityReport, DataContract, Owner
from .registry import ContractRegistry, RegistryError


class _RegisterRequest(BaseModel):
    contract: DataContract
    compatibility: CompatibilityMode = "backward"


class _DeprecateRequest(BaseModel):
    deprecation_uri: str


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.registry = ContractRegistry()
    # Shared httpx client for best-effort audit-stream emission. Always
    # created; the audit_stream module no-ops when AUDIT_STREAM_URL is unset.
    app.state.http_client = httpx.AsyncClient(
        headers={"User-Agent": f"data-contract-registry/{__version__} (+https://kineticgain.com)"},
    )
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(
    title="data-contract-registry",
    version=__version__,
    description=(
        "Schema registry for data contracts: semver, compatibility checks, "
        "ownership, freshness SLAs. Bridges to procurement-decision-api via "
        "POST /contracts/owners/from-decision-card."
    ),
    lifespan=_lifespan,
)


def _registry() -> ContractRegistry:
    """Typed accessor so mypy strict doesn't choke on app.state."""
    registry = app.state.registry
    assert isinstance(registry, ContractRegistry)
    return registry


def _http_client() -> httpx.AsyncClient:
    """Shared httpx client used by audit_stream.emit (best-effort)."""
    client = app.state.http_client
    assert isinstance(client, httpx.AsyncClient)
    return client


@app.get("/", tags=["meta"])
async def root() -> dict[str, Any]:
    return {
        "name": "data-contract-registry",
        "version": __version__,
        "description": (
            "Registers + checks data contracts. Compatibility modes follow Confluent: "
            "backward / forward / full / none."
        ),
        "endpoints": {
            "GET  /": "this page",
            "GET  /healthz": "liveness probe",
            "GET  /datasets": "list registered dataset IDs",
            "POST /contracts": "register a contract (checks compatibility first)",
            "POST /contracts/check": "dry-run compatibility check without registering",
            "GET  /contracts/{ds}/latest": "latest active contract for a dataset",
            "GET  /contracts/{ds}/versions": "full version history",
            "GET  /contracts/{ds}/versions/{v}": "one specific version",
            "POST /contracts/{ds}/versions/{v}/deprecate": "mark a version deprecated",
            "POST /contracts/{ds}/versions/{v}/archive": "archive a version",
            "POST /contracts/owners/from-decision-card": "Decision Card -> Owner list",
        },
    }


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/datasets", tags=["catalog"])
async def list_datasets() -> dict[str, list[str]]:
    return {"datasets": _registry().datasets()}


@app.post("/contracts", tags=["contracts"], status_code=201)
async def register_contract(req: _RegisterRequest) -> dict[str, Any]:
    try:
        report = _registry().register(req.contract, compatibility=req.compatibility)
    except RegistryError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    if not report.compatible:
        await audit_stream.emit(
            _http_client(),
            kind="contract_compatibility_failed",
            payload={
                "dataset_id": req.contract.dataset_id,
                "version": req.contract.version,
                "mode": report.mode,
                "issue_count": len(report.issues),
                "issues": [i.model_dump(mode="json") for i in report.issues],
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "compatible": False,
                "mode": report.mode,
                "issues": [i.model_dump(mode="json") for i in report.issues],
            },
        )
    await audit_stream.emit(
        _http_client(),
        kind="contract_promoted",
        payload={
            "dataset_id": req.contract.dataset_id,
            "version": req.contract.version,
            "mode": report.mode,
            "owners": [o.team for o in req.contract.owners],
        },
    )
    return {
        "status": "registered",
        "dataset_id": req.contract.dataset_id,
        "version": req.contract.version,
        "compatibility": report.model_dump(mode="json"),
    }


@app.post("/contracts/check", tags=["contracts"])
async def check_contract(req: _RegisterRequest) -> CompatibilityReport:
    return _registry().check(req.contract, compatibility=req.compatibility)


@app.get("/contracts/{dataset_id}/latest", tags=["contracts"])
async def latest_contract(dataset_id: str) -> DataContract:
    try:
        return _registry().latest(dataset_id)
    except RegistryError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.get("/contracts/{dataset_id}/versions", tags=["contracts"])
async def contract_history(dataset_id: str) -> list[DataContract]:
    try:
        return _registry().history(dataset_id)
    except RegistryError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.get("/contracts/{dataset_id}/versions/{version}", tags=["contracts"])
async def get_version(dataset_id: str, version: str) -> DataContract:
    try:
        return _registry().get(dataset_id, version)
    except RegistryError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.post("/contracts/{dataset_id}/versions/{version}/deprecate", tags=["contracts"])
async def deprecate_version(
    dataset_id: str,
    version: str,
    req: _DeprecateRequest,
) -> DataContract:
    try:
        contract = _registry().deprecate(dataset_id, version, deprecation_uri=req.deprecation_uri)
    except RegistryError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    await audit_stream.emit(
        _http_client(),
        kind="contract_deprecated",
        payload={
            "dataset_id": dataset_id,
            "version": version,
            "deprecation_uri": req.deprecation_uri,
        },
    )
    return contract


@app.post("/contracts/{dataset_id}/versions/{version}/archive", tags=["contracts"])
async def archive_version(dataset_id: str, version: str) -> DataContract:
    try:
        return _registry().archive(dataset_id, version)
    except RegistryError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@app.post("/contracts/owners/from-decision-card", tags=["bridge"])
async def owners_from_decision_card(card: dict[str, Any]) -> list[Owner]:
    """The cross-ecosystem hook — pull owners out of a Decision Card."""
    try:
        return contract_owner_from_decision_card(card)
    except (ValueError, ValidationError) as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
