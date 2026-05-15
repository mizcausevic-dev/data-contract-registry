"""
Compatibility checker — does new schema break consumers of old schema?

Modes follow the Confluent schema registry conventions:

    BACKWARD    new schema can read data produced by the previous schema
                (consumers can upgrade first)
    FORWARD     previous schema can read data produced by the new schema
                (producers can upgrade first)
    FULL        both
    NONE        anything goes; first-time onboarding only

For our six-type system the rules are:

    BACKWARD-breaking changes (new schema rejects old data):
      - removed a field that old data carried
      - changed a field's type
      - turned an optional field into required (old data missing it -> reject)
      - shrunk an enum (old enum value -> reject)

    FORWARD-breaking changes (old schema rejects new data):
      - added a required field old schema doesn't know about
        (only matters if old schema rejects unknown fields; we treat additions
         to enums as forward-compatible since extra values are fine for readers)

This is intentionally smaller than the Avro/Protobuf rule set — the point is
"can I promote this", not "let me prove every possible serialisation path."
"""

from __future__ import annotations

from typing import Literal

from .models import (
    CompatibilityIssue,
    CompatibilityReport,
    DataContract,
)

CompatibilityMode = Literal["backward", "forward", "full", "none"]


class CompatibilityChecker:
    """Stateless. Cheap to construct. Reuse one per process."""

    def check(
        self,
        previous: DataContract,
        proposed: DataContract,
        *,
        mode: CompatibilityMode = "backward",
    ) -> CompatibilityReport:
        if previous.dataset_id != proposed.dataset_id:
            raise ValueError(
                f"dataset_id mismatch: previous={previous.dataset_id!r} proposed={proposed.dataset_id!r}"
            )

        issues: list[CompatibilityIssue] = []
        issues.extend(self._version_issues(previous, proposed))
        issues.extend(self._owner_issues(proposed))
        issues.extend(self._primary_key_issues(previous, proposed))

        if mode in ("backward", "full"):
            issues.extend(self._backward_issues(previous, proposed))
        if mode in ("forward", "full"):
            issues.extend(self._forward_issues(previous, proposed))

        compatible = not any(i.severity == "error" for i in issues)
        return CompatibilityReport(compatible=compatible, mode=mode, issues=issues)

    # ---- structural checks (run regardless of mode) ---------------------

    def _version_issues(self, previous: DataContract, proposed: DataContract) -> list[CompatibilityIssue]:
        prev = _parse_semver(previous.version)
        new = _parse_semver(proposed.version)
        if new <= prev:
            return [
                CompatibilityIssue(
                    severity="error",
                    field=None,
                    kind="version_not_increasing",
                    message=(
                        f"new version {proposed.version!r} must be strictly greater than {previous.version!r}"
                    ),
                )
            ]
        return []

    def _owner_issues(self, proposed: DataContract) -> list[CompatibilityIssue]:
        if not proposed.owners:
            return [
                CompatibilityIssue(
                    severity="error",
                    field=None,
                    kind="owner_missing",
                    message="proposed contract must declare at least one owner",
                )
            ]
        return []

    def _primary_key_issues(self, previous: DataContract, proposed: DataContract) -> list[CompatibilityIssue]:
        if previous.primary_key != proposed.primary_key:
            return [
                CompatibilityIssue(
                    severity="error",
                    field=None,
                    kind="primary_key_changed",
                    message=(f"primary_key changed: {previous.primary_key} -> {proposed.primary_key}"),
                )
            ]
        return []

    # ---- backward / forward checks --------------------------------------

    def _backward_issues(self, previous: DataContract, proposed: DataContract) -> list[CompatibilityIssue]:
        issues: list[CompatibilityIssue] = []

        prev_fields = {f.name: f for f in previous.fields}
        new_fields = {f.name: f for f in proposed.fields}

        # Removed fields: a field that was in the old schema and isn't in the new.
        for name, prev in prev_fields.items():
            if name not in new_fields:
                issues.append(
                    CompatibilityIssue(
                        severity="error",
                        field=name,
                        kind="field_removed",
                        message=f"field {name!r} was removed; old data will fail validation",
                    )
                )
                continue
            new = new_fields[name]
            if new.type != prev.type:
                issues.append(
                    CompatibilityIssue(
                        severity="error",
                        field=name,
                        kind="field_type_changed",
                        message=(
                            f"field {name!r} type changed: {prev.type} -> {new.type}; "
                            "values from old schema may not round-trip"
                        ),
                    )
                )
            if not prev.required and new.required:
                issues.append(
                    CompatibilityIssue(
                        severity="error",
                        field=name,
                        kind="field_required_added",
                        message=(f"field {name!r} was optional, now required; old rows missing it will fail"),
                    )
                )
            if prev.enum and new.enum and set(new.enum) - set(prev.enum) != set(new.enum) - set(prev.enum):
                # Should never happen; guard kept for clarity.
                pass
            if prev.enum and new.enum:
                shrunk = set(prev.enum) - set(new.enum)
                if shrunk:
                    issues.append(
                        CompatibilityIssue(
                            severity="error",
                            field=name,
                            kind="field_enum_shrunk",
                            message=(
                                f"field {name!r} enum shrunk; removed values {sorted(map(str, shrunk))} "
                                "may appear in old data"
                            ),
                        )
                    )
        return issues

    def _forward_issues(self, previous: DataContract, proposed: DataContract) -> list[CompatibilityIssue]:
        issues: list[CompatibilityIssue] = []
        prev_fields = {f.name: f for f in previous.fields}
        new_fields = {f.name: f for f in proposed.fields}

        for name, new in new_fields.items():
            if name not in prev_fields and new.required:
                issues.append(
                    CompatibilityIssue(
                        severity="error",
                        field=name,
                        kind="field_required_added",
                        message=(
                            f"required field {name!r} added; consumers on the old schema "
                            "won't know how to populate it"
                        ),
                    )
                )
        return issues


def _parse_semver(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)
