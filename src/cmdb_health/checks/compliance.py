"""Compliance checks: relationship governance and ownership."""

from __future__ import annotations

from cmdb_health.checks.base import Check, CheckContext
from cmdb_health.config import HealthConfig
from cmdb_health.models import CheckResult, Dimension, Finding, Severity
from cmdb_health.normalize import is_blank


class InvalidRelationshipCheck(Check):
    check_id = "INVALID_RELATIONSHIP"
    title = "Invalid relationship types"
    dimension = Dimension.COMPLIANCE
    description = (
        "Relationships whose type is not on the allow-list, whose type is not permitted for the "
        "parent/child class pair, or that point at a CI that does not exist."
    )

    def run(self, ctx: CheckContext) -> CheckResult:
        cfg = ctx.config
        index = ctx.dataset.by_sys_id()
        allowed = set(cfg.allowed_relationship_types)
        findings: list[Finding] = []
        involved: set[str] = set()

        for rel in ctx.dataset.relationships:
            parent = index.get(rel.parent)
            child = index.get(rel.child)
            anchor = parent or child or {"sys_id": rel.parent, "name": "", "sys_class_name": ""}
            involved.add(str(anchor.get("sys_id")))
            if parent is None or child is None:
                if not ctx.dataset.complete_scope:
                    continue  # other end is probably a class we did not load
                missing = "parent" if parent is None else "child"
                findings.append(
                    self.finding(
                        anchor,
                        f"Relationship {rel.sys_id} references a {missing} CI that does not exist",
                        Severity.HIGH,
                        relationship=rel.sys_id,
                        type=rel.type,
                    )
                )
                continue
            if rel.type not in allowed:
                findings.append(
                    self.finding(
                        parent,
                        f"Relationship type '{rel.type}' is not on the allow-list",
                        relationship=rel.sys_id,
                        child=rel.child,
                        type=rel.type,
                    )
                )
                continue
            permitted = permitted_types_for_pair(
                cfg, str(parent.get("sys_class_name", "")), str(child.get("sys_class_name", ""))
            )
            if permitted is not None and rel.type not in permitted:
                findings.append(
                    self.finding(
                        parent,
                        f"'{rel.type}' is not a suggested relationship between "
                        f"{parent.get('sys_class_name')} and {child.get('sys_class_name')} "
                        f"(expected one of: {', '.join(sorted(permitted))})",
                        Severity.LOW,
                        relationship=rel.sys_id,
                        child=rel.child,
                        type=rel.type,
                    )
                )
        return self.result(len(involved), findings)


def permitted_types_for_pair(cfg: HealthConfig, parent_cls: str, child_cls: str) -> set[str] | None:
    """Union of types allowed by every rule matching the class pair, or None if no rule applies."""
    permitted: set[str] = set()
    found = False
    for rule in cfg.relationship_rules:
        if cfg.is_a(parent_cls, rule["parent"]) and cfg.is_a(child_cls, rule["child"]):
            permitted.update(rule["types"])
            found = True
    return permitted if found else None


class UnownedCICheck(Check):
    check_id = "UNOWNED_CI"
    title = "Unowned CIs"
    dimension = Dimension.COMPLIANCE
    description = "CIs with none of the configured ownership fields (default: support_group, owned_by) populated."

    def run(self, ctx: CheckContext) -> CheckResult:
        fields = ctx.config.ownership_fields
        cis = ctx.active_cis
        findings = []
        for ci in cis:
            if all(is_blank(ci.get(f)) for f in fields):
                findings.append(self.finding(ci, f"No owner: {' and '.join(fields)} are empty", fields=fields))
        return self.result(len(cis), findings)
