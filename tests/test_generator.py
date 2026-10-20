import importlib.util
import json

from cmdb_health.engine import run_health_checks
from cmdb_health.sources.local import load_local

from conftest import ROOT


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_synthetic_cmdb.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_is_deterministic_and_injects_every_issue(tmp_path):
    gen = _load_generator()
    gen.main(["--count", "60", "--seed", "7", "--out", str(tmp_path / "a")])
    gen.main(["--count", "60", "--seed", "7", "--out", str(tmp_path / "b")])
    a = json.loads((tmp_path / "a" / "cis.json").read_text())
    b = json.loads((tmp_path / "b" / "cis.json").read_text())
    assert a == b

    data = load_local(tmp_path / "a" / "cis.json", tmp_path / "a" / "relationships.csv")
    from conftest import AS_OF

    report = run_health_checks(data, as_of=AS_OF)
    assert all(r.failing_cis > 0 for r in report.results), [r.to_dict() for r in report.results]


def test_committed_sample_matches_generator(tmp_path):
    gen = _load_generator()
    gen.main(["--out", str(tmp_path)])
    assert (tmp_path / "cis.json").read_text() == (ROOT / "sample_data" / "cis.json").read_text()
