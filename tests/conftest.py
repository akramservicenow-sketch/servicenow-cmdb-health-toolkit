from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cmdb_health.checks.base import CheckContext
from cmdb_health.config import HealthConfig
from cmdb_health.models import Dataset, Relationship

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
AS_OF = datetime(2026, 10, 1, tzinfo=UTC)


def server(sys_id: str, **overrides: Any) -> dict[str, Any]:
    ci = {
        "sys_id": sys_id,
        "name": f"srv-{sys_id}",
        "sys_class_name": "cmdb_ci_linux_server",
        "operational_status": "1",
        "install_status": "1",
        "serial_number": f"SER{sys_id.upper()}",
        "mac_address": "02" + hashlib.sha256(sys_id.encode()).hexdigest()[:10],
        "manufacturer": "Synthetic Vendor A",
        "model_id": "model-1",
        "location": "DC-East-01",
        "os": "Linux",
        "ip_address": "10.0.0.1",
        "support_group": "grp-linux-ops",
        "owned_by": "user-0001",
        "last_discovered": "2026-09-30 10:00:00",
    }
    ci.update(overrides)
    return ci


def make_ctx(cis: list[dict[str, Any]], rels: list[Relationship] | None = None, **cfg: Any) -> CheckContext:
    config = HealthConfig(**cfg)
    return CheckContext(dataset=Dataset(cis=cis, relationships=rels or []), config=config, as_of=AS_OF)


def rel(parent: str, child: str, rel_type: str = "Depends on::Used by", sys_id: str | None = None) -> Relationship:
    return Relationship(sys_id=sys_id or f"r-{parent}-{child}", parent=parent, child=child, type=rel_type)


@pytest.fixture
def sample_paths() -> tuple[Path, Path]:
    return SAMPLE / "cis.json", SAMPLE / "relationships.json"
