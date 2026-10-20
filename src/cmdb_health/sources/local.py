"""Load CIs and relationships from local JSON or CSV exports.

Accepted JSON shapes:

* ``{"cis": [...], "relationships": [...]}`` (single bundle file)
* ``{"result": [...]}`` (Table API response saved to disk)
* ``{"records": [...]}`` (legacy JSONv2 export)
* ``[...]`` (bare list)

CSV files are read with a header row; column names map to field names.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from cmdb_health.models import Dataset, Relationship


class DataSourceError(ValueError):
    pass


def _read_records(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    if suffix == ".json":
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    raise DataSourceError(f"Unsupported file type '{suffix}' for {path} (use .json or .csv)")


def _unwrap(data: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("result", "records"):
            if isinstance(data.get(key), list):
                return data[key]
    raise DataSourceError(f"Could not find a record list in {path}")


def _flatten_reference(value: Any) -> Any:
    """Table API reference fields may arrive as ``{"value": ..., "link": ...}``."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def normalise_ci(record: dict[str, Any]) -> dict[str, Any]:
    return {k: _flatten_reference(v) for k, v in record.items()}


def to_relationship(record: dict[str, Any]) -> Relationship:
    rec = normalise_ci(record)
    rel_type = rec.get("type.name") or rec.get("type_name") or rec.get("type") or ""
    return Relationship(
        sys_id=str(rec.get("sys_id", "")),
        parent=str(rec.get("parent", "")),
        child=str(rec.get("child", "")),
        type=str(rel_type),
    )


def _validate_cis(cis: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    cleaned = [normalise_ci(r) for r in cis]
    missing = [i for i, ci in enumerate(cleaned) if not ci.get("sys_id")]
    if missing:
        raise DataSourceError(f"{len(missing)} CI record(s) in {origin} have no sys_id (first at index {missing[0]})")
    return cleaned


def load_local(cis_path: str | Path, relationships_path: str | Path | None = None) -> Dataset:
    cis_path = Path(cis_path)
    data = _read_records(cis_path)
    if isinstance(data, dict) and "cis" in data:
        cis = _validate_cis(data["cis"], str(cis_path))
        rels = [to_relationship(r) for r in data.get("relationships", [])]
    else:
        cis = _validate_cis(_unwrap(data, cis_path), str(cis_path))
        rels = []
    if relationships_path is not None:
        rel_path = Path(relationships_path)
        rels = [to_relationship(r) for r in _unwrap(_read_records(rel_path), rel_path)]
    return Dataset(cis=cis, relationships=rels)
