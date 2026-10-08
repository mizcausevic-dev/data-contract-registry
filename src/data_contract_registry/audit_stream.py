"""
Optional audit-stream-py integration.

When `AUDIT_STREAM_URL` is set to the sink base URL (or its `/events`
endpoint), this module fires governance events at the normalized endpoint.
`AUDIT_STREAM_TOKEN` supplies the sink's bearer credential.
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

The sink contract is aligned with procurement-decision-api.audit_stream and
policy-as-code-engine.audit_stream.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def events_url() -> str | None:
    """Normalize a sink base or exact `/events` URL without forwarding URL credentials."""
    raw = base_url()
    if raw is None:
        return None
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    if parsed.scheme == "http":
        try:
            if not ipaddress.ip_address(hostname or "").is_loopback:
                return None
        except ValueError:
            return None
    path = parsed.path.rstrip("/")
    if not path.endswith("/events"):
        path += "/events"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def audit_token() -> str | None:
    """Return only a token accepted by the sink's configured-token syntax."""
    token = os.environ.get("AUDIT_STREAM_TOKEN", "")
    return token if re.fullmatch(r"[!-~]{32,}", token) else None


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
    if not is_enabled():
        return
    url = events_url()
    token = audit_token()
    if url is None or token is None:
        logger.warning("audit-stream emit failed (kind=%s; error=InvalidConfiguration)", kind)
        return

    body = {
        "kind": kind,
        "source": "data-contract-registry",
        "payload": payload,
    }
    try:
        response = await client.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
            timeout=timeout_s(),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as err:
        logger.warning(
            "audit-stream emit failed (kind=%s; error=HTTPStatusError; status=%s)",
            kind,
            err.response.status_code,
        )
    except (httpx.HTTPError, OSError) as err:
        # Exception strings can contain URLs and credentials from the
        # operator-supplied sink URL. Log only the event kind and error class.
        logger.warning("audit-stream emit failed (kind=%s; error=%s)", kind, type(err).__name__)
