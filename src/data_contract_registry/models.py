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

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


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
    enum: list[str | int | float | bool] | None = Field(
        default=None,
        description="If set, the field value must be one of these.",
    )
    deprecated: bool = False

    @model_validator(mode="after")
    def _check_enum(self) -> DataField:
        if not self.name.strip():
            raise ValueError("field name must not be blank")
        if self.enum is None:
            return self
        if not self.enum:
            raise ValueError("enum must contain at least one value")
        if self.type in ("timestamp", "json"):
            raise ValueError(f"enum is not supported for {self.type} fields")
        for value in self.enum:
            valid = (
                (self.type == "string" and type(value) is str)
                or (self.type == "integer" and type(value) is int)
                or (self.type == "number" and type(value) in (int, float))
                or (self.type == "boolean" and type(value) is bool)
            )
            if not valid or (type(value) is float and not math.isfinite(value)):
                raise ValueError(f"enum values must match field type {self.type}")
        if len(set(self.enum)) != len(self.enum):
            raise ValueError("enum values must be unique")
        return self


class Owner(StrictModel):
    """One owner of a contract — usually a team."""

    team: str = Field(..., min_length=1)
    contact: str | None = Field(
        default=None,
        description="Slack channel, pager group, or email.",
    )

    @model_validator(mode="after")
    def _check_owner(self) -> Owner:
        if not self.team.strip():
            raise ValueError("owner team must not be blank")
        if self.contact is not None and not self.contact.strip():
            raise ValueError("owner contact must not be blank")
        return self


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

    Stable identity is `(dataset_id, version)`. Version numbers use semver:

        MAJOR   indicates an incompatible change, but does not bypass checks
        MINOR   new optional field, new enum value
        PATCH   description fix, owner update, no schema change
    """

    dataset_id: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., max_length=64, description="Semver like '1.2.0'.")
    description: str | None = None
    fields: list[DataField] = Field(..., min_length=1)
    owners: list[Owner] = Field(..., min_length=1)
    freshness_sla: FreshnessSLA | None = None
    status: ContractStatus = "draft"
    deprecation_uri: str | None = None
    primary_key: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_invariants(self) -> DataContract:
        if not self.dataset_id.strip():
            raise ValueError("dataset_id must not be blank")
        if not SEMVER_RE.match(self.version):
            raise ValueError(f"version must match MAJOR.MINOR.PATCH; got {self.version!r}")
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique within a contract")
        fields_by_name = {field.name: field for field in self.fields}
        for key in self.primary_key:
            if key not in fields_by_name:
                raise ValueError(f"primary_key field {key!r} is not declared in fields")
            if not fields_by_name[key].required:
                raise ValueError(f"primary_key field {key!r} must be required")
        if len(self.primary_key) != len(set(self.primary_key)):
            raise ValueError("primary_key fields must be unique")
        if self.status == "deprecated" and not (self.deprecation_uri or "").strip():
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
        "field_required_removed",
        "field_enum_shrunk",
        "field_enum_expanded",
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
