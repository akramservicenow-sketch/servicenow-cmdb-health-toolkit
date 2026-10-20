"""Normalisation helpers used for duplicate detection and identification."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

_HEX12 = re.compile(r"^[0-9a-f]{12}$")
_NON_ALNUM = re.compile(r"[^0-9A-Z]")
_INVALID_MACS = {"000000000000", "ffffffffffff"}


def normalize_mac(value: str | None) -> str | None:
    """Return a MAC as 12 lowercase hex chars, or ``None`` if unusable.

    Accepts ``AA:BB:CC:DD:EE:FF``, ``aa-bb-cc-dd-ee-ff``, ``aabb.ccdd.eeff``
    (Cisco style) and bare hex. Broadcast and all-zero addresses are rejected.
    """
    if not value:
        return None
    cleaned = re.sub(r"[\s:\-.]", "", str(value)).lower()
    if not _HEX12.match(cleaned) or cleaned in _INVALID_MACS:
        return None
    return cleaned


def normalize_serial(value: str | None, junk: Iterable[str] = ()) -> str | None:
    """Upper-case, strip separators, and drop placeholder serial numbers."""
    if value is None:
        return None
    cleaned = _NON_ALNUM.sub("", str(value).upper())
    junk_set = {_NON_ALNUM.sub("", j.upper()) for j in junk}
    if not cleaned or cleaned in junk_set:
        return None
    return cleaned


def normalize_name(value: str | None, strip_domain: bool = True) -> str | None:
    """Case-fold a CI name and optionally reduce an FQDN to its host label."""
    if not value:
        return None
    cleaned = str(value).strip().casefold()
    if strip_domain and "." in cleaned and not _looks_like_ip(cleaned):
        cleaned = cleaned.split(".", 1)[0]
    return cleaned or None


def _looks_like_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def is_blank(value: object) -> bool:
    """Treat ``None``, empty strings and whitespace as missing."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, dict):  # reference field returned as {"value": ...}
        return is_blank(value.get("value"))
    return False


_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d")


def parse_sn_datetime(value: str | None) -> datetime | None:
    """Parse ServiceNow's ``YYYY-MM-DD HH:MM:SS`` (UTC) and ISO variants."""
    if is_blank(value):
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
