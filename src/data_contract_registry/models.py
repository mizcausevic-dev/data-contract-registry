"""
Pydantic v2 models for data contracts.

A `DataContract` is the unit of agreement between a data producer and one or
more consumers. The schema is intentionally small — six field types covering
~99% of real-world dataset columns — plus the metadata that always matters:

    - owners              who to wake up
    - freshness SLA       how stale is too stale
    - status              draft / active / deprecated / archived
    - deprecation_uri     when status == "deprecated", where the migration plan lives

Versions are full snapshots (not diffs); the registry holds the version history.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


FieldType = Literal["string", "integer", "number", "boolean", "timestamp", "json"]
"""Six canonical primitives. `json` is the escape hatch for nested payloads."""

ContractStatus = Literal["draft", "active", "deprecated", "archived"]


class DataField(StrictModel):
    """One column / attribute in the contract."""

    name: str = Field(..., min_length=1)
    type: FieldType
    required: bool = True
    description: str | None = None
    enum: list[str | int | bool] | None = Field(
        default=None,
        description="If set, the field value must be one of these.",
    )
    deprecated: bool = False


class Owner(StrictModel):
    """One owner of a contract — usually a team."""

    team: str = Field(..., min_length=1)
    contact: str | None = Field(
        default=None,
        description="Slack channel, pager group, or email.",
    )


class FreshnessSLA(StrictModel):
    """How stale the dataset is allowed to be before it's considered broken."""

    max_lag_seconds: int = Field(..., gt=0)
    measurement: str = Field(
        default="event_time",
        description="Field whose age is measured: 'event_time', 'ingested_at', etc.",
    )


class DataContract(StrictModel):
    """
    The whole contract document.

    Stable identity is `(dataset_id, version)`. Versions follow semver:

        MAJOR   incompatible change (removed field, renamed field, type change)
        MINOR   new optional field, new enum value
        PATCH   description fix, owner update, no schema change
    """

    dataset_id: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., description="Semver like '1.2.0'.")
    description: str | None = None
    fields: list[DataField] = Field(..., min_length=1)
    owners: list[Owner] = Field(..., min_length=1)
    freshness_sla: FreshnessSLA | None = None
    status: ContractStatus = "draft"
    deprecation_uri: str | None = None
    primary_key: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_invariants(self) -> DataContract:
        if not SEMVER_RE.match(self.version):
            raise ValueError(f"version must match MAJOR.MINOR.PATCH; got {self.version!r}")
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique within a contract")
        for key in self.primary_key:
            if key not in names:
                raise ValueError(f"primary_key field {key!r} is not declared in fields")
        if self.status == "deprecated" and not self.deprecation_uri:
            raise ValueError("status='deprecated' requires deprecation_uri")
        return self

    def field(self, name: str) -> DataField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ---------------------------------------------------------------------------
# Compatibility outputs
# ---------------------------------------------------------------------------


class CompatibilityIssue(StrictModel):
    """A single problem flagged by the compatibility checker."""

    severity: Literal["error", "warning"]
    field: str | None = None
    kind: Literal[
        "field_removed",
        "field_renamed",
        "field_type_changed",
        "field_required_added",
        "field_enum_shrunk",
        "version_not_increasing",
        "owner_missing",
        "primary_key_changed",
    ]
    message: str


class CompatibilityReport(StrictModel):
    """Result of `CompatibilityChecker.check`."""

    compatible: bool
    mode: str
    issues: list[CompatibilityIssue]

    @property
    def errors(self) -> list[CompatibilityIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[CompatibilityIssue]:
        return [i for i in self.issues if i.severity == "warning"]
