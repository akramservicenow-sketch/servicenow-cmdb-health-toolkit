import csv
import json

from cmdb_health.cli import main
from cmdb_health.engine import run_health_checks
from cmdb_health.models import Dataset
from cmdb_health.reports import render_console, render_html, write_csv, write_json

from conftest import AS_OF, server


def _report():
    cis = [
        server("a", name="<script>alert(1)</script>", serial_number="DUP1"),
        server("b", name="=HYPERLINK(evil)", serial_number="DUP1"),
    ]
    return run_health_checks(Dataset(cis=cis), as_of=AS_OF, source="unit")


def test_json_report_structure(tmp_path):
    path = write_json(_report(), tmp_path / "r.json")
    data = json.loads(path.read_text())
    assert set(data["summary"]["dimension_scores"]) == {"completeness", "correctness", "compliance"}
    assert data["findings"][0]["severity"] == "high"
    assert len(data["checks"]) == 7


def test_csv_report_neutralises_formula_injection(tmp_path):
    path = write_csv(_report(), tmp_path / "r.csv")
    rows = list(csv.DictReader(path.open()))
    names = {r["ci_name"] for r in rows}
    assert "'=HYPERLINK(evil)" in names
    assert "=HYPERLINK(evil)" not in names


def test_html_report_is_self_contained_and_escaped():
    html = render_html(_report())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "http://" not in html and "https://" not in html
    assert "Correctness" in html


def test_console_summary_lists_scores():
    text = render_console(_report(), max_findings=3)
    assert "OVERALL SCORE" in text
    assert "DUPLICATE_CI" in text


def test_cli_scan_writes_all_formats(sample_paths, tmp_path, capsys):
    cis, rels = sample_paths
    code = main(
        [
            "scan",
            "--cis", str(cis),
            "--relationships", str(rels),
            "--as-of", "2026-10-01",
            "--format", "console,json,csv,html",
            "--output-dir", str(tmp_path),
        ]
    )  # fmt: skip
    assert code == 0
    assert "OVERALL SCORE" in capsys.readouterr().out
    for name in ("cmdb_health.json", "cmdb_health_findings.csv", "cmdb_health.html"):
        assert (tmp_path / name).stat().st_size > 0


def test_cli_fail_under_returns_2(sample_paths, tmp_path):
    cis, rels = sample_paths
    args = ["scan", "--cis", str(cis), "--relationships", str(rels), "--as-of", "2026-10-01", "--fail-under", "99.9"]
    assert main(args) == 2


def test_cli_errors_are_reported_cleanly(capsys):
    assert main(["scan"]) == 1
    assert "--cis is required" in capsys.readouterr().err


def test_cli_servicenow_source_requires_env(monkeypatch, capsys):
    monkeypatch.delenv("SN_INSTANCE_URL", raising=False)
    assert main(["scan", "--source", "servicenow"]) == 1
    assert "SN_INSTANCE_URL" in capsys.readouterr().err


def test_cli_checks_lists_catalog(capsys):
    assert main(["checks"]) == 0
    out = capsys.readouterr().out
    assert "IDENTIFICATION_RULE" in out and "UNOWNED_CI" in out
