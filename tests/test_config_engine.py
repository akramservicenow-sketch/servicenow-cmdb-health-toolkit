import pytest

from cmdb_health.config import HealthConfig, load_config
from cmdb_health.engine import run_health_checks, score_dimensions
from cmdb_health.models import CheckResult, Dataset, Dimension, Finding, Severity

from conftest import AS_OF, server


def test_lineage_and_mandatory_inheritance():
    cfg = HealthConfig()
    assert cfg.lineage("cmdb_ci_linux_server")[:3] == ["cmdb_ci_linux_server", "cmdb_ci_server", "cmdb_ci_computer"]
    required = cfg.mandatory_for("cmdb_ci_linux_server")
    assert {"name", "serial_number", "os"} <= set(required)
    assert cfg.lineage("unknown_class") == ["unknown_class", "cmdb_ci"]


def test_load_config_merges_and_overrides(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('stale_days = 7\n[mandatory_attributes]\ncmdb_ci_netgear = ["firmware_version"]\n')
    cfg = load_config(path)
    assert cfg.stale_days == 7
    assert cfg.mandatory_attributes["cmdb_ci_netgear"] == ["firmware_version"]
    assert "cmdb_ci_hardware" in cfg.mandatory_attributes  # defaults kept


def test_load_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("stael_days = 7\n")
    with pytest.raises(ValueError, match="stael_days"):
        load_config(path)


def test_example_config_is_valid():
    from conftest import ROOT

    cfg = load_config(ROOT / "config" / "cmdb-health.example.toml")
    assert cfg.dimension_weights["correctness"] == 1.5


def test_score_dimensions_weighted():
    failing = [Finding("A", Dimension.COMPLETENESS, Severity.LOW, str(i), "", "", "m") for i in range(5)]
    results = [
        CheckResult("A", "A", Dimension.COMPLETENESS, 10, failing),
        CheckResult("B", "B", Dimension.CORRECTNESS, 0, []),
    ]
    dims, overall = score_dimensions(results, {"completeness": 1, "correctness": 3, "compliance": 1})
    assert dims == {"completeness": 50.0, "correctness": 100.0}
    assert overall == 87.5  # (50*1 + 100*3) / 4; compliance has no checks so its weight is ignored


def test_engine_end_to_end_and_disabled_checks():
    data = Dataset(cis=[server("a"), server("b", serial_number="SERA")])
    report = run_health_checks(data, HealthConfig(disabled_checks=["orphan_ci"]), as_of=AS_OF)
    ids = [r.check_id for r in report.results]
    assert "ORPHAN_CI" not in ids
    dup = next(r for r in report.results if r.check_id == "DUPLICATE_CI")
    assert dup.score == 0.0
    assert report.to_dict()["summary"]["severity_counts"]["high"] >= 2
    assert 0 <= report.overall_score < 100
