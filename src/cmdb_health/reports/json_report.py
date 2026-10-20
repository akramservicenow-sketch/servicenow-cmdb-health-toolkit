"""JSON report writer."""

from __future__ import annotations

import json
from pathlib import Path

from cmdb_health.engine import HealthReport


def write_json(report: HealthReport, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
    return path
