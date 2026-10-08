"""
data-contract-registry — schema registry for data contracts.

This package checks selected schema-promotion rules; it does not prove that
every downstream reader accepts every row. Contracts carry fields, owners,
freshness SLA, and deprecation metadata.

Two surfaces:

    Library:  `from data_contract_registry import DataContract, ContractRegistry`
    HTTP:     `uvicorn data_contract_registry.app:app` (optional `[api]` extra)

Compatibility modes use the conventional direction names:

    BACKWARD      new schema can read data produced by the previous schema
    FORWARD       previous schema can read data produced by the new schema
    FULL          both of the above
    NONE          anything goes (use for first-time onboarding only)
"""

from __future__ import annotations

from .compatibility import CompatibilityChecker, CompatibilityMode
from .from_decision_card import contract_owner_from_decision_card
from .models import (
    CompatibilityReport,
    ContractStatus,
    DataContract,
    DataField,
    FieldType,
    FreshnessSLA,
    Owner,
)
from .registry import ContractRegistry, RegistryError

__version__ = "0.2.0"

__all__ = [
    "CompatibilityChecker",
    "CompatibilityMode",
    "CompatibilityReport",
    "ContractRegistry",
    "ContractStatus",
    "DataContract",
    "DataField",
    "FieldType",
    "FreshnessSLA",
    "Owner",
    "RegistryError",
    "__version__",
    "contract_owner_from_decision_card",
]
