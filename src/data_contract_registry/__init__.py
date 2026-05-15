"""
data-contract-registry — schema registry for data contracts.

This package answers one question for a data team: *can this producer ship the
new schema without breaking any downstream consumer it has a contract with?*
Contracts carry the schema itself, plus the things that always matter and
usually get lost in slack — owners, freshness SLA, deprecation policy.

Two surfaces:

    Library:  `from data_contract_registry import DataContract, ContractRegistry`
    HTTP:     `uvicorn data_contract_registry.app:app` (optional `[api]` extra)

Compatibility modes follow the Confluent schema-registry conventions so this
slots into existing data org playbooks:

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

__version__ = "0.1.0"

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
