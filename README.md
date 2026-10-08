# data-contract-registry

[![CI](https://github.com/mizcausevic-dev/data-contract-registry/actions/workflows/ci.yml/badge.svg)](https://github.com/mizcausevic-dev/data-contract-registry/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**In-memory reference registry for data contracts.** Semver version history, compatibility reports (backward / forward / full), declared owners, and freshness SLAs. It does not authenticate callers, approve contracts, persist state across restarts, or prove that downstream readers accept every row.

The headline endpoint is `POST /contracts` — register a new version, get back a deterministic compatibility report or a 422 with every breaking change called out by field name and kind.

---

## Why

The thing that gets data teams paged at 2am isn't a missing test. It's a producer who quietly removed `ltv` because "we never use it anymore" while three downstream dashboards still join on it. Schema registries (Confluent, Buf, etc.) solved this for streaming and gRPC; data pipelines need the same hardness in a shape that fits the things data teams actually argue about:

- **owners** — who do I page when this dataset goes stale
- **freshness SLA** — when does "stale" become "broken"
- **primary key** — changes are flagged regardless of the version bump
- **enum drift** — narrowing breaks backward checks; widening breaks forward checks
- **deprecation policy** — flag a version with the URI of the migration plan; don't delete it

This package is the smallest thing that does all of those.

---

## Install

```bash
pip install data-contract-registry
# with the FastAPI surface:
pip install "data-contract-registry[api]"
```

Python 3.11+. Runtime deps: `pydantic`, `PyYAML`, and `httpx` for the optional audit sink.

---

## Library quickstart

```python
from data_contract_registry import (
    ContractRegistry,
    DataContract,
    DataField,
    Owner,
)

registry = ContractRegistry()

v1 = DataContract(
    dataset_id="users.daily_active",
    version="1.0.0",
    primary_key=["user_id", "active_date"],
    owners=[Owner(team="growth-platform", contact="#growth-platform")],
    fields=[
        DataField(name="user_id",     type="string"),
        DataField(name="active_date", type="timestamp"),
        DataField(name="plan",        type="string", enum=["free", "pro", "enterprise"]),
        DataField(name="ltv",         type="number", required=False),
    ],
    status="active",
)
registry.register(v1)

# Compatible promotion (added an optional field).
v1_1 = v1.model_copy(update={
    "version": "1.1.0",
    "fields": [*v1.fields, DataField(name="signup_source", type="string", required=False)],
})
report = registry.register(v1_1)
print(report.compatible)   # True

# Incompatible promotion — removing a field breaks backward compatibility.
v2 = v1.model_copy(update={"version": "2.0.0", "fields": [f for f in v1.fields if f.name != "ltv"]})
report = registry.register(v2)
print(report.compatible)               # False
print(report.errors[0].kind)           # "field_removed"
print(report.errors[0].message)        # "field 'ltv' was removed; old data will fail validation"
```

---

## Compatibility modes

| Mode       | Meaning |
| ---------- | --- |
| `backward` | Checks whether a new schema may reject previous rows. **Default.** Consumers upgrade first. |
| `forward`  | Checks whether a previous schema may reject new rows. Producers upgrade first. |
| `full`     | Both. |
| `none`     | Skip field checks; version and primary-key rules still apply. Use only with a reviewed migration. |

These are conservative schema-promotion rules, not full row validation or a substitute for a consumer test. Optional new fields are permitted by policy; a strict parser may still reject them. Compatibility is checked against the latest registered version, even if it is archived, so versions cannot move backward.

The checks the engine knows how to flag (each carries a structured `kind` so you can build CI gates around specific failures):

| Kind                       | Severity | Mode |
| -------------------------- | -------- | --- |
| `field_removed`            | error    | backward |
| `field_type_changed`       | error    | backward / forward |
| `field_required_added`     | error    | backward (optional→required or new required field) / forward (new required field) |
| `field_required_removed`   | error    | forward (required→optional or removed) |
| `field_enum_shrunk`        | error    | backward (including introducing an enum) |
| `field_enum_expanded`      | error    | forward (including removing an enum) |
| `primary_key_changed`      | error    | always |
| `version_not_increasing`   | error    | always |
| `owner_missing`            | error    | always |

---

## FastAPI surface

```bash
pip install "data-contract-registry[api]"
uvicorn data_contract_registry.app:app --host 127.0.0.1 --port 8090
```

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/` | Service info. |
| GET | `/healthz` | Liveness probe. |
| GET | `/datasets` | List registered dataset IDs. |
| POST | `/contracts` | Register / promote a contract. 422 with a structured issue list when incompatible. |
| POST | `/contracts/check` | Dry-run compatibility check — does **not** register. |
| GET | `/contracts/{ds}/latest` | Latest **active** contract for a dataset. |
| GET | `/contracts/{ds}/versions` | Full version history. |
| GET | `/contracts/{ds}/versions/{v}` | One specific version. |
| POST | `/contracts/{ds}/versions/{v}/deprecate` | Mark deprecated with a migration URI. |
| POST | `/contracts/{ds}/versions/{v}/archive` | Archive a version (history preserved). |
| POST | `/contracts/owners/from-decision-card` | **Cross-ecosystem hook** — suggest owner records from Decision Card fields. |

Contracts are process-local memory only. Restarts erase them; multiple workers do not share state. No caller authentication, authorization, tenant isolation, approval workflow, rate limiting, or durable audit trail is provided. Keep this reference server on loopback with synthetic or public data. A customer-facing deployment needs an external trust boundary and durable store.

`AUDIT_STREAM_URL` optionally sends best-effort event summaries to an operator-configured endpoint. Failures do not block writes, so this is not a durable audit record. The event includes dataset ID, version and issue kinds, but omits owner contacts and field-level compatibility messages.

---

## The cross-ecosystem hook

The bridge maps `buyer.name` and optional `decision_maker.role/name` to **candidate** owner records. It does not validate the Decision Card, decision status, signatures, buyer identity, or on-call authority. A data steward must confirm the owners and contact before registration. Even a pending, rejected, or withdrawn card can produce the same candidates; the mapping is not an approval gate.

```bash
curl -X POST http://localhost:8090/contracts/owners/from-decision-card \
  -H 'Content-Type: application/json' \
  -d @decision-card.json
# -> [
#   {"team": "Springfield USD",                            "contact": "#data-platform"},
#   {"team": "Director of Data (Alex Chen)",               "contact": null}
# ]
```

Review and correct that list before putting it into `DataContract.owners`. `decision_maker.authority` describes approval authority and is not treated as a paging contact.

---

## YAML authoring

```yaml
# contracts/users-daily-active.yaml
dataset_id: users.daily_active
version: "1.0.0"
owners:
  - team: growth-platform
    contact: "#growth-platform"
freshness_sla:
  max_lag_seconds: 86400
fields:
  - {name: user_id,      type: string}
  - {name: active_date,  type: timestamp}
  - {name: plan,         type: string, enum: [free, pro, enterprise]}
```

Hand-author in YAML, validate in CI, register from Python. The matching [serialized JSON fixture](examples/contract.json) is an exported `DataContract` usable by CSV and SQL consumers. A [number enum fixture](examples/contract-number-enum.json) demonstrates finite fractional values for SQL projection:

```python
import yaml
from pathlib import Path
from data_contract_registry import ContractRegistry, DataContract

raw = yaml.safe_load(Path("contracts/users-daily-active.yaml").read_text())
ContractRegistry().register(DataContract.model_validate(raw))
```

---

## Tests

```bash
pip install -e ".[dev]"
ruff check src tests scripts && ruff format --check src tests scripts
mypy src
pytest -v
```

CI matrix runs Python 3.11 / 3.12 / 3.13.

---

## Related in this ecosystem

- **[procurement-decision-api](https://github.com/mizcausevic-dev/procurement-decision-api)** — drafts the Decision Cards this registry pulls owners from.
- **[policy-as-code-engine](https://github.com/mizcausevic-dev/policy-as-code-engine)** — a separate Decision Card policy prototype; no DataContract enforcement integration is verified here.
- **[slo-budget-tracker](https://github.com/mizcausevic-dev/slo-budget-tracker)** — wire your freshness SLA into the same monitoring story.
- More at [kineticgain.com](https://kineticgain.com/).

---

## License

MIT. See [LICENSE](LICENSE).
