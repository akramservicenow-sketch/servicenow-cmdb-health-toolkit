"""Runs the configured checks and rolls results up into a scorecard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cmdb_health import __version__
from cmdb_health.checks import CheckContext, get_checks
from cmdb_health.config import HealthConfig
from cmdb_health.models import SEVERITY_ORDER, CheckResult, Dataset, Dimension, Finding


@dataclass
class HealthReport:
    generated_at: datetime
    as_of: datetime
    source: str
    total_cis: int
    in_scope_cis: int
    total_relationships: int
    results: list[CheckResult]
    dimension_scores: dict[str, float]
    overall_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def findings(self) -> list[Finding]:
        items = [f for r in self.results for f in r.findings]
        return sorted(items, key=lambda f: (SEVERITY_ORDER[f.severity], f.check_id, f.ci_name))

    def severity_counts(self) -> dict[str, int]:
        counts = {"high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "cmdb-health",
            "version": __version__,
            "generated_at": self.generated_at.isoformat(),
            "as_of": self.as_of.isoformat(),
            "source": self.source,
            "summary": {
                "total_cis": self.total_cis,
                "in_scope_cis": self.in_scope_cis,
                "total_relationships": self.total_relationships,
                "overall_score": self.overall_score,
                "dimension_scores": self.dimension_scores,
                "severity_counts": self.severity_counts(),
            },
            "checks": [r.to_dict() for r in self.results],
            "findings": [f.to_dict() for f in self.findings],
            "metadata": self.metadata,
        }


def score_dimensions(results: list[CheckResult], weights: dict[str, float]) -> tuple[dict[str, float], float]:
    """Dimension score = mean of its check scores; overall = weighted mean of dimensions."""
    dimension_scores: dict[str, float] = {}
    for dim in Dimension:
        scores = [r.score for r in results if r.dimension == dim]
        if scores:
            dimension_scores[dim.value] = round(sum(scores) / len(scores), 1)
    total_weight = sum(weights.get(d, 0.0) for d in dimension_scores)
    if total_weight <= 0:
        return dimension_scores, 100.0
    overall = sum(score * weights.get(d, 0.0) for d, score in dimension_scores.items()) / total_weight
    return dimension_scores, round(overall, 1)


def run_health_checks(
    dataset: Dataset,
    config: HealthConfig | None = None,
    as_of: datetime | None = None,
    source: str = "local",
) -> HealthReport:
    config = config or HealthConfig()
    as_of = as_of or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    ctx = CheckContext(dataset=dataset, config=config, as_of=as_of)
    results = [check.run(ctx) for check in get_checks(config.disabled_checks)]
    dimension_scores, overall = score_dimensions(results, config.dimension_weights)
    return HealthReport(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        source=source,
        total_cis=len(dataset.cis),
        in_scope_cis=len(ctx.active_cis),
        total_relationships=len(dataset.relationships),
        results=results,
        dimension_scores=dimension_scores,
        overall_score=overall,
    )
