"""
In-memory contract registry.

Holds many contracts by `(dataset_id, version)` and exposes the moves data
teams actually make:

    register      promote a new version after compatibility passes
    latest        give me the freshest contract for this dataset
    history       give me every version
    deprecate     mark a version deprecated with a migration URI
    archive       remove from active rotation (history preserved)

Concurrency: a single `threading.Lock` around the dict. Real deployments
would swap this for a SQL backend; the protocol is small enough that doing
so is mechanical.
"""

from __future__ import annotations

from threading import Lock

from .compatibility import CompatibilityChecker, CompatibilityMode
from .models import CompatibilityReport, DataContract


class RegistryError(Exception):
    """Raised by `ContractRegistry` for caller-facing failures."""


class ContractRegistry:
    """Thread-safe in-memory registry. Cheap to share across threads."""

    __slots__ = ("_checker", "_contracts", "_lock")

    def __init__(self, *, checker: CompatibilityChecker | None = None) -> None:
        self._contracts: dict[str, list[DataContract]] = {}
        self._checker = checker or CompatibilityChecker()
        self._lock = Lock()

    # ---- writes ---------------------------------------------------------

    def register(
        self,
        contract: DataContract,
        *,
        compatibility: CompatibilityMode = "backward",
    ) -> CompatibilityReport:
        """
        Register a new version of a contract.

        If there's no existing version for this `dataset_id`, the contract is
        accepted unconditionally (a compatible-by-vacuous-truth report is returned).

        If there is, the new version is checked against the most recent active
        version. The registration only proceeds if the report's `compatible` is
        True.
        """
        with self._lock:
            history = self._contracts.setdefault(contract.dataset_id, [])
            existing = next((c for c in reversed(history) if c.status == "active"), None)
            if existing is None and history:
                # Fall back to the most recent of any status.
                existing = history[-1]

            if existing is None:
                history.append(contract)
                return CompatibilityReport(compatible=True, mode=compatibility, issues=[])

            if existing.version == contract.version:
                raise RegistryError(
                    f"version {contract.version!r} of {contract.dataset_id!r} is already registered"
                )

            report = self._checker.check(existing, contract, mode=compatibility)
            if not report.compatible:
                return report

            history.append(contract)
            return report

    def deprecate(
        self,
        dataset_id: str,
        version: str,
        *,
        deprecation_uri: str,
    ) -> DataContract:
        with self._lock:
            history = self._contracts.get(dataset_id)
            if not history:
                raise RegistryError(f"unknown dataset_id: {dataset_id!r}")
            for i, c in enumerate(history):
                if c.version == version:
                    updated = c.model_copy(
                        update={"status": "deprecated", "deprecation_uri": deprecation_uri}
                    )
                    history[i] = updated
                    return updated
            raise RegistryError(f"{dataset_id!r} has no version {version!r}")

    def archive(self, dataset_id: str, version: str) -> DataContract:
        with self._lock:
            history = self._contracts.get(dataset_id)
            if not history:
                raise RegistryError(f"unknown dataset_id: {dataset_id!r}")
            for i, c in enumerate(history):
                if c.version == version:
                    updated = c.model_copy(update={"status": "archived"})
                    history[i] = updated
                    return updated
            raise RegistryError(f"{dataset_id!r} has no version {version!r}")

    # ---- reads ----------------------------------------------------------

    def latest(self, dataset_id: str, *, include_non_active: bool = False) -> DataContract:
        with self._lock:
            history = self._contracts.get(dataset_id)
            if not history:
                raise RegistryError(f"unknown dataset_id: {dataset_id!r}")
            if include_non_active:
                return history[-1]
            for c in reversed(history):
                if c.status == "active":
                    return c
            raise RegistryError(f"{dataset_id!r} has no active version")

    def get(self, dataset_id: str, version: str) -> DataContract:
        with self._lock:
            history = self._contracts.get(dataset_id)
            if not history:
                raise RegistryError(f"unknown dataset_id: {dataset_id!r}")
            for c in history:
                if c.version == version:
                    return c
            raise RegistryError(f"{dataset_id!r} has no version {version!r}")

    def history(self, dataset_id: str) -> list[DataContract]:
        with self._lock:
            history = self._contracts.get(dataset_id)
            if not history:
                raise RegistryError(f"unknown dataset_id: {dataset_id!r}")
            return list(history)

    def datasets(self) -> list[str]:
        with self._lock:
            return list(self._contracts.keys())

    def __contains__(self, dataset_id: object) -> bool:
        with self._lock:
            return dataset_id in self._contracts

    # ---- dry-run --------------------------------------------------------

    def check(
        self,
        contract: DataContract,
        *,
        compatibility: CompatibilityMode = "backward",
    ) -> CompatibilityReport:
        """Check a proposed contract WITHOUT registering it."""
        with self._lock:
            history = self._contracts.get(contract.dataset_id)
            existing = next((c for c in reversed(history or []) if c.status == "active"), None)
        if existing is None:
            return CompatibilityReport(compatible=True, mode=compatibility, issues=[])
        return self._checker.check(existing, contract, mode=compatibility)
