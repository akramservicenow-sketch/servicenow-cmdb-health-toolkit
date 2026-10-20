import pytest

from cmdb_health.config import DEFAULT_JUNK_SERIALS
from cmdb_health.normalize import is_blank, normalize_mac, normalize_name, normalize_serial, parse_sn_datetime


@pytest.mark.parametrize(
    "raw",
    ["02:1A:2B:3C:4D:5E", "02-1a-2b-3c-4d-5e", "021a.2b3c.4d5e", "021A2B3C4D5E", " 02:1a:2b:3c:4d:5e "],
)
def test_mac_formats_normalise_to_same_value(raw):
    assert normalize_mac(raw) == "021a2b3c4d5e"


@pytest.mark.parametrize("raw", [None, "", "00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF", "zz:11:22:33:44:55", "0211"])
def test_unusable_macs_are_rejected(raw):
    assert normalize_mac(raw) is None


def test_serial_normalisation_strips_separators_and_case():
    assert normalize_serial("syn-abc 123") == "SYNABC123"


@pytest.mark.parametrize("junk", ["To Be Filled By O.E.M.", "N/A", "unknown", "0", "  "])
def test_placeholder_serials_are_treated_as_missing(junk):
    assert normalize_serial(junk, DEFAULT_JUNK_SERIALS) is None


def test_name_strips_domain_but_not_ip():
    assert normalize_name("WEB01.example.internal") == "web01"
    assert normalize_name("10.0.0.5") == "10.0.0.5"
    assert normalize_name("WEB01.example.internal", strip_domain=False) == "web01.example.internal"


def test_parse_servicenow_datetime_formats():
    assert parse_sn_datetime("2026-09-01 12:30:00").day == 1
    assert parse_sn_datetime("2026-09-01T12:30:00Z").hour == 12
    assert parse_sn_datetime("") is None
    assert parse_sn_datetime("not a date") is None


def test_is_blank_handles_reference_dicts():
    assert is_blank({"value": "", "link": "x"})
    assert not is_blank({"value": "abc"})
    assert is_blank("   ")
    assert not is_blank(0)
