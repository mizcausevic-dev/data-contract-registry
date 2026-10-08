"""
Optional audit-stream-py integration.

When the `AUDIT_STREAM_URL` env var is set, this module fires governance
events at `{AUDIT_STREAM_URL}/events` for the moments the service produces.
Best-effort: a failed POST is logged, not raised — audit-stream outages
must never block contract registration or deprecation.

Event kinds this service emits:
    contract_promoted              on POST /contracts when the new version
                                   is compatible and successfully registered
    contract_compatibility_failed  on POST /contracts when the compatibility
                                   check fails (HTTP 422). This is the
                                   "we tried to ship a breaking change"
                                   governance signal — record it.
    contract_deprecated            on POST /contracts/{ds}/versions/{v}/deprecate

Same opt-in pattern as procurement-decision-api.audit_stream,
aeo-validator-service.audit_stream, and policy-as-code-engine.audit_stream.
Identical config envvars.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 2.5
MAX_TIMEOUT_S = 10.0
logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """True when AUDIT_STREAM_URL is set to a non-empty value."""
    return bool(os.environ.get("AUDIT_STREAM_URL", "").strip())


def base_url() -> str | None:
    """Stripped audit-stream base URL, or None when disabled."""
    raw = os.environ.get("AUDIT_STREAM_URL", "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def timeout_s() -> float:
    """Configured per-call timeout. Defaults to 2.5s."""
    raw = os.environ.get("AUDIT_STREAM_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    if not math.isfinite(value):
        return DEFAULT_TIMEOUT_S
    return min(MAX_TIMEOUT_S, max(0.1, value))


async def emit(
    client: httpx.AsyncClient,
    *,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """Fire one event. Silent no-op when AUDIT_STREAM_URL is unset."""
    url = base_url()
    if url is None:
        return

    body = {
        "kind": kind,
        "source": "data-contract-registry",
        "payload": payload,
    }
    try:
        response = await client.post(
            f"{url}/events",
            json=body,
            timeout=timeout_s(),
        )
        response.raise_for_status()
    except (httpx.HTTPError, OSError) as err:
        # Exception strings can contain URLs and credentials from the
        # operator-supplied sink URL. Log only the event kind and error class.
        logger.warning("audit-stream emit failed (kind=%s; error=%s)", kind, type(err).__name__)
