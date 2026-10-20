"""Core data structures shared by sources, checks and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Dimension(StrEnum):
    """The three ServiceNow CMDB Health dimensions."""

    COMPLETENESS = "completeness"
    CORRECTNESS = "correctness"
    COMPLIANCE = "compliance"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}


@dataclass(frozen=True)
class Relationship:
    """A row from ``cmdb_rel_ci`` reduced to what the checks need."""

    sys_id: str
    parent: str
    child: str
    type: str


@dataclass
class Dataset:
    """CIs (as plain dicts keyed by field name) plus their relationships."""

    cis: list[dict[str, Any]]
    relationships: list[Relationship] = field(default_factory=list)
    # False when only some CI classes were loaded: a relationship whose other
    # end is missing may simply point outside the loaded scope.
    complete_scope: bool = True

    def by_sys_id(self) -> dict[str, dict[str, Any]]:
        return {ci["sys_id"]: ci for ci in self.cis if ci.get("sys_id")}


@dataclass
class Finding:
    check_id: str
    dimension: Dimension
    severity: Severity
    ci_sys_id: str
    ci_name: str
    ci_class: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dimension"] = self.dimension.value
        data["severity"] = self.severity.value
        return data


@dataclass
class CheckResult:
    """Outcome of one check: the findings plus the population it evaluated."""

    check_id: str
    title: str
    dimension: Dimension
    evaluated: int
    findings: list[Finding]

    @property
    def failing_cis(self) -> int:
        return len({f.ci_sys_id for f in self.findings})

    @property
    def score(self) -> float:
        """Percentage of evaluated CIs with no finding from this check."""
        if self.evaluated == 0:
            return 100.0
        passing = max(self.evaluated - self.failing_cis, 0)
        return round(100.0 * passing / self.evaluated, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "dimension": self.dimension.value,
            "evaluated": self.evaluated,
            "failing_cis": self.failing_cis,
            "findings": len(self.findings),
            "score": self.score,
        }
