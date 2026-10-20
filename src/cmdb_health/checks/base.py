"""Base class and shared context for health checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from cmdb_health.config import HealthConfig
from cmdb_health.models import CheckResult, Dataset, Dimension, Finding, Severity


@dataclass
class CheckContext:
    dataset: Dataset
    config: HealthConfig
    as_of: datetime

    @property
    def active_cis(self) -> list[dict[str, Any]]:
        """CIs that are in scope (retired/excluded install statuses removed)."""
        excluded = {str(s) for s in self.config.exclude_install_status}
        return [ci for ci in self.dataset.cis if str(ci.get("install_status", "")) not in excluded]


class Check(ABC):
    check_id: ClassVar[str]
    title: ClassVar[str]
    dimension: ClassVar[Dimension]
    description: ClassVar[str]
    default_severity: ClassVar[Severity] = Severity.MEDIUM

    @abstractmethod
    def run(self, ctx: CheckContext) -> CheckResult: ...

    def finding(
        self,
        ci: dict[str, Any],
        message: str,
        severity: Severity | None = None,
        **details: Any,
    ) -> Finding:
        return Finding(
            check_id=self.check_id,
            dimension=self.dimension,
            severity=severity or self.default_severity,
            ci_sys_id=str(ci.get("sys_id", "")),
            ci_name=str(ci.get("name") or ""),
            ci_class=str(ci.get("sys_class_name") or ""),
            message=message,
            details=details,
        )

    def result(self, evaluated: int, findings: list[Finding]) -> CheckResult:
        return CheckResult(
            check_id=self.check_id,
            title=self.title,
            dimension=self.dimension,
            evaluated=evaluated,
            findings=findings,
        )
