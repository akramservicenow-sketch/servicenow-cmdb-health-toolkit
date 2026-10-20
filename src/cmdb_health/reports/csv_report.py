"""CSV writer: one row per finding, suitable for import into a remediation tracker."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from cmdb_health.engine import HealthReport

COLUMNS = ["severity", "dimension", "check_id", "ci_sys_id", "ci_name", "ci_class", "message", "details"]


def write_csv(report: HealthReport, path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for finding in report.findings:
            row = finding.to_dict()
            row["details"] = json.dumps(row["details"], sort_keys=True, default=str)
            writer.writerow({c: _safe(row[c]) for c in COLUMNS})
    return path


def _safe(value: object) -> str:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text
