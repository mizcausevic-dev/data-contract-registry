# data-contract-registry

[![CI](https://github.com/mizcausevic-dev/data-contract-registry/actions/workflows/ci.yml/badge.svg)](https://github.com/mizcausevic-dev/data-contract-registry/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Schema registry for data contracts.** Semver versioning, compatibility checks (backward / forward / full), declared owners, freshness SLAs. The "you can't promote a new dataset version without an approved contract" pattern, lifted from API governance and aimed at data pipelines.

The headline endpoint is `POST /contracts` — register a new version, get back a deterministic compatibility report or a 422 with every breaking change called out by field name and kind.

---

## Why

The thing that gets data teams paged at 2am isn't a missing test. It's a producer who quietly removed `ltv` because "we never use it anymore" while three downstream dashboards still join on it. Schema registries (Confluent, Buf, etc.) solved this for streaming and gRPC; data pipelines need the same hardness in a shape that fits the things data teams actually argue about:

- **owners** — who do I page when this dataset goes stale
- **freshness SLA** — when does "stale" become "broken"
- **primary key** — changing it is a `MAJOR`, not a `MINOR`
- **enum drift** — adding a value is fine; removing one is a backward-compatibility break
- **deprecation policy** — flag a version with the URI of the migration plan; don't delete it

This package is the smallest thing that does all of those.

---

## Install

```bash
pip install data-contract-registry
# with the FastAPI surface:
pip install "data-contract-registry[api]"
```

Python 3.11+. Runtime deps: `pydantic` + `PyYAML`.

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
| `backward` | New schema can read data produced by the previous schema. **Default.** Consumers upgrade first. |
| `forward`  | Previous schema can read data produced by the new schema. Producers upgrade first. |
| `full`     | Both. |
| `none`     | Anything goes. First-time onboarding only. |

The checks the engine knows how to flag (each carries a structured `kind` so you can build CI gates around specific failures):

| Kind                       | Severity | Mode |
| -------------------------- | -------- | --- |
| `field_removed`            | error    | backward |
| `field_type_changed`       | error    | backward |
| `field_required_added`     | error    | backward (optional→required) **or** forward (new required field) |
| `field_enum_shrunk`        | error    | backward |
| `primary_key_changed`      | error    | always |
| `version_not_increasing`   | error    | always |
| `owner_missing`            | error    | always |

---

## FastAPI surface

```bash
pip install "data-contract-registry[api]"
uvicorn data_contract_registry.app:app --port 8090
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
| POST | `/contracts/owners/from-decision-card` | **Cross-ecosystem hook** — pull owners out of a Decision Card. |

Bundles are held in-memory by default. For restart-safe storage, swap `_BundleStore`'s implementation; the protocol is small.

---

## The cross-ecosystem hook

The third hook in the portfolio (after `procurement-decision-api` → `policy-as-code-engine` and the Suite → Decision Intelligence bridge). When a buyer approves a vendor whose data product the team will consume, the Decision Card's `buyer.name` + `decision_maker` are **the right answer** to "who owns the contract on our side":

```bash
curl -X POST http://localhost:8090/contracts/owners/from-decision-card \
  -H 'Content-Type: application/json' \
  -d @decision-card.json
# -> [
#   {"team": "Springfield USD",                            "contact": "#data-platform"},
#   {"team": "Director of Data (Alex Chen)",               "contact": null}
# ]
```

Drop that list straight into `DataContract.owners` and the registration carries paging info the team didn't have to re-type.

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

Hand-author in YAML, validate in CI, register from Python:

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
ruff check src tests && ruff format --check src tests
mypy src
pytest -v
```

CI matrix runs Python 3.11 / 3.12 / 3.13.

---

## Related in this ecosystem

- **[procurement-decision-api](https://github.com/mizcausevic-dev/procurement-decision-api)** — drafts the Decision Cards this registry pulls owners from.
- **[policy-as-code-engine](https://github.com/mizcausevic-dev/policy-as-code-engine)** — pair with this registry to enforce contracts at request time.
- **[slo-budget-tracker](https://github.com/mizcausevic-dev/slo-budget-tracker)** — wire your freshness SLA into the same monitoring story.
- More at [kineticgain.com](https://kineticgain.com/).

---

## License

MIT. See [LICENSE](LICENSE).
