"""Check registry."""

from __future__ import annotations

from cmdb_health.checks.base import Check, CheckContext
from cmdb_health.checks.completeness import MandatoryAttributesCheck
from cmdb_health.checks.compliance import InvalidRelationshipCheck, UnownedCICheck
from cmdb_health.checks.correctness import (
    DuplicateCICheck,
    IdentificationRuleCheck,
    OrphanCICheck,
    StaleCICheck,
)

ALL_CHECKS: list[type[Check]] = [
    MandatoryAttributesCheck,
    DuplicateCICheck,
    OrphanCICheck,
    StaleCICheck,
    IdentificationRuleCheck,
    InvalidRelationshipCheck,
    UnownedCICheck,
]


def get_checks(disabled: list[str] | None = None) -> list[Check]:
    disabled_set = {d.upper() for d in (disabled or [])}
    return [cls() for cls in ALL_CHECKS if cls.check_id not in disabled_set]


__all__ = ["ALL_CHECKS", "Check", "CheckContext", "get_checks"]
