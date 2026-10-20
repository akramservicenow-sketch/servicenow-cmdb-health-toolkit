import json

import pytest

from cmdb_health.sources.local import DataSourceError, load_local


def test_load_committed_sample(sample_paths):
    cis, rels = sample_paths
    data = load_local(cis, rels)
    assert len(data.cis) > 50
    assert len(data.relationships) > 40
    assert all(r.type for r in data.relationships)


def test_bundle_json_with_reference_dicts(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(
        json.dumps(
            {
                "cis": [{"sys_id": "1", "name": "a", "support_group": {"value": "g1", "link": "https://x"}}],
                "relationships": [
                    {"sys_id": "r", "parent": {"value": "1"}, "child": "2", "type.name": "Runs on::Runs"}
                ],
            }
        )
    )
    data = load_local(path)
    assert data.cis[0]["support_group"] == "g1"
    assert data.relationships[0].parent == "1"
    assert data.relationships[0].type == "Runs on::Runs"


def test_csv_sources(tmp_path):
    cis = tmp_path / "cis.csv"
    cis.write_text("sys_id,name,sys_class_name\n1,a,cmdb_ci_server\n2,b,cmdb_ci_server\n")
    rels = tmp_path / "rels.csv"
    rels.write_text("sys_id,parent,child,type\nr1,1,2,Depends on::Used by\n")
    data = load_local(cis, rels)
    assert [c["name"] for c in data.cis] == ["a", "b"]
    assert data.relationships[0].child == "2"


def test_missing_sys_id_is_an_error(tmp_path):
    path = tmp_path / "cis.json"
    path.write_text(json.dumps([{"name": "no id"}]))
    with pytest.raises(DataSourceError, match="no sys_id"):
        load_local(path)


def test_unsupported_extension(tmp_path):
    path = tmp_path / "cis.xml"
    path.write_text("<x/>")
    with pytest.raises(DataSourceError, match="Unsupported"):
        load_local(path)
