"""Health-check configuration.

Defaults are deliberately modest and CSDM-flavoured. Every value can be
overridden with a TOML file (see ``config/cmdb-health.example.toml``).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

# Child class -> parent class. Used so that rules defined for a parent class
# (e.g. cmdb_ci_hardware) also apply to its descendants, the way class-level
# rules work on the platform.
DEFAULT_CLASS_HIERARCHY: dict[str, str] = {
    "cmdb_ci_hardware": "cmdb_ci",
    "cmdb_ci_computer": "cmdb_ci_hardware",
    "cmdb_ci_server": "cmdb_ci_computer",
    "cmdb_ci_linux_server": "cmdb_ci_server",
    "cmdb_ci_win_server": "cmdb_ci_server",
    "cmdb_ci_vm_instance": "cmdb_ci",
    "cmdb_ci_netgear": "cmdb_ci_hardware",
    "cmdb_ci_ip_switch": "cmdb_ci_netgear",
    "cmdb_ci_ip_router": "cmdb_ci_netgear",
    "cmdb_ci_appl": "cmdb_ci",
    "cmdb_ci_db_instance": "cmdb_ci_appl",
    "cmdb_ci_service": "cmdb_ci",
    "cmdb_ci_service_auto": "cmdb_ci_service",
    "cmdb_ci_service_discovered": "cmdb_ci_service_auto",
    "cmdb_ci_service_technical": "cmdb_ci_service",
    "service_offering": "cmdb_ci_service",
}

DEFAULT_MANDATORY_ATTRIBUTES: dict[str, list[str]] = {
    "cmdb_ci": ["name", "sys_class_name", "operational_status"],
    "cmdb_ci_hardware": ["serial_number", "manufacturer", "model_id", "location"],
    "cmdb_ci_computer": ["os", "ip_address"],
    "cmdb_ci_appl": ["version"],
    "cmdb_ci_service": ["service_classification"],
}

DEFAULT_ALLOWED_RELATIONSHIP_TYPES: list[str] = [
    "Depends on::Used by",
    "Runs on::Runs",
    "Hosted on::Hosts",
    "Contains::Contained by",
    "Connects to::Connected by",
    "Virtualized by::Virtualizes",
    "Members::Member of",
    "Provided by::Provides",
]

# (parent_class, child_class) -> allowed types. Pairs not listed fall back to
# the global allow-list above.
DEFAULT_RELATIONSHIP_RULES: list[dict[str, Any]] = [
    {"parent": "cmdb_ci_appl", "child": "cmdb_ci_computer", "types": ["Runs on::Runs"]},
    {"parent": "cmdb_ci_appl", "child": "cmdb_ci_vm_instance", "types": ["Runs on::Runs"]},
    {
        "parent": "cmdb_ci_service",
        "child": "cmdb_ci_appl",
        "types": ["Depends on::Used by", "Contains::Contained by"],
    },
    {"parent": "cmdb_ci_vm_instance", "child": "cmdb_ci_server", "types": ["Virtualized by::Virtualizes"]},
]

# Ordered identifier entries per class, mirroring Identification and
# Reconciliation Engine (IRE) rules. ``strong`` marks entries that uniquely
# identify a device; a fallback to a weak entry is reported as a warning.
DEFAULT_IDENTIFICATION_RULES: dict[str, list[dict[str, Any]]] = {
    "cmdb_ci_hardware": [
        {"attributes": ["serial_number"], "strong": True},
        {"attributes": ["mac_address"], "strong": True},
        {"attributes": ["name"], "strong": False},
    ],
    "cmdb_ci_vm_instance": [
        {"attributes": ["object_id"], "strong": True},
        {"attributes": ["name"], "strong": False},
    ],
    "cmdb_ci_appl": [
        {"attributes": ["name", "version"], "strong": True},
        {"attributes": ["name"], "strong": False},
    ],
    "cmdb_ci_service": [{"attributes": ["name"], "strong": True}],
}

DEFAULT_JUNK_SERIALS: list[str] = [
    "",
    "0",
    "NA",
    "N/A",
    "NONE",
    "NULL",
    "UNKNOWN",
    "DEFAULTSTRING",
    "TOBEFILLEDBYOEM",
    "SYSTEMSERIALNUMBER",
    "123456789",
]


@dataclass
class HealthConfig:
    stale_days: int = 30
    stale_check_classes: list[str] = field(default_factory=lambda: ["cmdb_ci_hardware", "cmdb_ci_vm_instance"])
    orphan_exempt_classes: list[str] = field(default_factory=lambda: ["cmdb_ci_service"])
    ownership_fields: list[str] = field(default_factory=lambda: ["support_group", "owned_by"])
    exclude_install_status: list[str] = field(default_factory=lambda: ["7"])  # 7 = Retired
    strip_domain_for_duplicates: bool = True
    class_hierarchy: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CLASS_HIERARCHY))
    mandatory_attributes: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_MANDATORY_ATTRIBUTES.items()}
    )
    allowed_relationship_types: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_RELATIONSHIP_TYPES))
    relationship_rules: list[dict[str, Any]] = field(
        default_factory=lambda: [dict(r) for r in DEFAULT_RELATIONSHIP_RULES]
    )
    identification_rules: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {k: [dict(e) for e in v] for k, v in DEFAULT_IDENTIFICATION_RULES.items()}
    )
    junk_serials: list[str] = field(default_factory=lambda: list(DEFAULT_JUNK_SERIALS))
    dimension_weights: dict[str, float] = field(
        default_factory=lambda: {"completeness": 1.0, "correctness": 1.0, "compliance": 1.0}
    )
    disabled_checks: list[str] = field(default_factory=list)

    # ---- class hierarchy helpers -------------------------------------------------

    def lineage(self, cls: str) -> list[str]:
        """Return ``cls`` followed by its ancestors, ending at ``cmdb_ci``."""
        chain: list[str] = []
        current: str | None = cls
        seen: set[str] = set()
        while current and current not in seen:
            chain.append(current)
            seen.add(current)
            current = self.class_hierarchy.get(current)
        if "cmdb_ci" not in chain:
            chain.append("cmdb_ci")
        return chain

    def is_a(self, cls: str, ancestor: str) -> bool:
        return ancestor in self.lineage(cls)

    def mandatory_for(self, cls: str) -> list[str]:
        attrs: list[str] = []
        for c in reversed(self.lineage(cls)):
            for attr in self.mandatory_attributes.get(c, []):
                if attr not in attrs:
                    attrs.append(attr)
        return attrs

    def identification_rule_for(self, cls: str) -> tuple[str, list[dict[str, Any]]] | None:
        for c in self.lineage(cls):
            if c in self.identification_rules:
                return c, self.identification_rules[c]
        return None


def load_config(path: str | Path | None = None) -> HealthConfig:
    """Load defaults, then overlay values from a TOML file if given."""
    cfg = HealthConfig()
    if path is None:
        return cfg
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    known = {f.name for f in fields(HealthConfig)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
    for key, value in data.items():
        current = getattr(cfg, key)
        if isinstance(current, dict) and isinstance(value, dict):
            # Merge class-keyed maps so users can extend rather than replace.
            merged = dict(current)
            merged.update(value)
            setattr(cfg, key, merged)
        else:
            setattr(cfg, key, value)
    return cfg
