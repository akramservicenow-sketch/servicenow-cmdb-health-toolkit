"""Plain-text console summary (no colour codes, so it is safe to pipe to files)."""

from __future__ import annotations

from cmdb_health.engine import HealthReport


def _bar(score: float, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_console(report: HealthReport, max_findings: int = 10) -> str:
    lines = [
        "CMDB Health Report",
        "=" * 60,
        f"Source:          {report.source}",
        f"As of:           {report.as_of:%Y-%m-%d %H:%M} UTC",
        f"CIs loaded:      {report.total_cis} ({report.in_scope_cis} in scope)",
        f"Relationships:   {report.total_relationships}",
        "",
        f"OVERALL SCORE    {report.overall_score:5.1f}  [{_bar(report.overall_score)}]",
    ]
    for dim, score in report.dimension_scores.items():
        lines.append(f"  {dim.title():<14} {score:5.1f}  [{_bar(score)}]")
    lines += ["", f"{'Check':<28} {'Dimension':<13} {'Eval':>5} {'Fail':>5} {'Score':>6}", "-" * 60]
    for r in report.results:
        lines.append(f"{r.check_id:<28} {r.dimension.value:<13} {r.evaluated:>5} {r.failing_cis:>5} {r.score:>6.1f}")
    counts = report.severity_counts()
    lines += [
        "",
        f"Findings: {sum(counts.values())} (high {counts['high']}, medium {counts['medium']}, low {counts['low']})",
    ]
    if report.findings and max_findings > 0:
        lines.append(f"Top {min(max_findings, len(report.findings))} findings:")
        for f in report.findings[:max_findings]:
            lines.append(f"  [{f.severity.value.upper():<6}] {f.check_id:<20} {f.ci_name or f.ci_sys_id}: {f.message}")
    return "\n".join(lines) + "\n"
