from cmdb_health.checks.completeness import MandatoryAttributesCheck
from cmdb_health.checks.compliance import InvalidRelationshipCheck, UnownedCICheck
from cmdb_health.checks.correctness import DuplicateCICheck, IdentificationRuleCheck, OrphanCICheck, StaleCICheck
from cmdb_health.models import Dataset, Severity

from conftest import make_ctx, rel, server


def test_duplicates_by_serial_ignore_formatting():
    ctx = make_ctx([server("a", serial_number="SYN-1234"), server("b", serial_number="syn1234"), server("c")])
    result = DuplicateCICheck().run(ctx)
    assert {f.ci_sys_id for f in result.findings} == {"a", "b"}
    assert result.findings[0].details["matched_on"]["serial_number"]["duplicates_of"] == ["b"]


def test_duplicates_by_mac_across_notations():
    ctx = make_ctx([server("a", mac_address="02:aa:bb:cc:dd:ee"), server("b", mac_address="02aa.bbcc.ddee")])
    result = DuplicateCICheck().run(ctx)
    assert result.failing_cis == 2
    assert "mac_address" in result.findings[0].details["matched_on"]


def test_duplicates_by_name_and_class_strip_domain():
    ctx = make_ctx([server("a", name="web01"), server("b", name="WEB01.example.internal")])
    assert DuplicateCICheck().run(ctx).failing_cis == 2


def test_same_name_in_different_class_is_not_duplicate():
    ctx = make_ctx([server("a", name="web01"), server("b", name="web01", sys_class_name="cmdb_ci_win_server")])
    assert DuplicateCICheck().run(ctx).failing_cis == 0


def test_placeholder_serials_do_not_create_duplicate_groups():
    ctx = make_ctx([server("a", serial_number="N/A"), server("b", serial_number="n/a")])
    assert DuplicateCICheck().run(ctx).failing_cis == 0


def test_retired_cis_are_out_of_scope():
    ctx = make_ctx([server("a", serial_number="X1"), server("b", serial_number="X1", install_status="7")])
    result = DuplicateCICheck().run(ctx)
    assert result.evaluated == 1
    assert result.failing_cis == 0


def test_orphans_and_exempt_classes():
    cis = [
        server("a"),
        server("b"),
        server("c"),
        {"sys_id": "svc", "name": "Svc", "sys_class_name": "cmdb_ci_service_discovered"},
    ]
    result = OrphanCICheck().run(make_ctx(cis, [rel("a", "b")]))
    assert [f.ci_sys_id for f in result.findings] == ["c"]
    assert result.evaluated == 3  # the service class is exempt by default


def test_stale_and_never_discovered():
    cis = [
        server("fresh"),
        server("old", last_discovered="2026-07-01 00:00:00"),
        server("never", last_discovered=""),
        {"sys_id": "app", "name": "app", "sys_class_name": "cmdb_ci_appl"},  # not discoverable class
    ]
    result = StaleCICheck().run(make_ctx(cis, stale_days=30))
    by_id = {f.ci_sys_id: f for f in result.findings}
    assert set(by_id) == {"old", "never"}
    assert by_id["never"].severity is Severity.HIGH
    assert by_id["old"].details["days_since_discovery"] == 92
    assert result.evaluated == 3


def test_mandatory_attributes_inherit_through_hierarchy():
    ci = server("a", os="", location="", serial_number="To Be Filled By O.E.M.")
    result = MandatoryAttributesCheck().run(make_ctx([ci, server("b")]))
    assert result.failing_cis == 1
    missing = result.findings[0].details["missing_attributes"]
    assert set(missing) == {"os", "location", "serial_number"}
    assert result.findings[0].severity is Severity.HIGH


def test_unowned_ci():
    ctx = make_ctx([server("a", support_group="", owned_by=None), server("b", support_group="")])
    result = UnownedCICheck().run(ctx)
    assert [f.ci_sys_id for f in result.findings] == ["a"]


def test_invalid_relationship_variants():
    app = {"sys_id": "app", "name": "app", "sys_class_name": "cmdb_ci_appl"}
    cis = [app, server("a"), server("b")]
    rels = [
        rel("app", "a", "Runs on::Runs", "ok"),
        rel("app", "b", "Owns::Owned by", "bad-type"),
        rel("app", "a", "Depends on::Used by", "wrong-pair"),
        rel("a", "ghost", "Connects to::Connected by", "dangling"),
    ]
    result = InvalidRelationshipCheck().run(make_ctx(cis, rels))
    by_rel = {f.details["relationship"]: f for f in result.findings}
    assert set(by_rel) == {"bad-type", "wrong-pair", "dangling"}
    assert by_rel["dangling"].severity is Severity.HIGH
    assert by_rel["wrong-pair"].severity is Severity.LOW


def test_dangling_relationships_skipped_for_partial_scope():
    ctx = make_ctx([server("a")], [rel("a", "outside-scope", "Connects to::Connected by")])
    ctx.dataset = Dataset(cis=ctx.dataset.cis, relationships=ctx.dataset.relationships, complete_scope=False)
    assert InvalidRelationshipCheck().run(ctx).findings == []


def test_identification_rule_simulation():
    cis = [
        server("strong"),
        server("mac-only", serial_number=""),  # falls to mac entry: still strong
        server("weak", serial_number="", mac_address=""),  # only name left
        server("none", serial_number="", mac_address="", name=""),
        {"sys_id": "x", "name": "x", "sys_class_name": "cmdb_ci_unmapped_class"},  # no rule
    ]
    result = IdentificationRuleCheck().run(make_ctx(cis))
    by_id = {f.ci_sys_id: f for f in result.findings}
    assert set(by_id) == {"weak", "none"}
    assert by_id["none"].severity is Severity.HIGH
    assert by_id["weak"].details["matched_entry"] == ["name"]
    assert result.evaluated == 4
