"""Correctness checks: duplicates, orphans, staleness, identification."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from cmdb_health.checks.base import Check, CheckContext
from cmdb_health.models import CheckResult, Dimension, Finding, Severity
from cmdb_health.normalize import is_blank, normalize_mac, normalize_name, normalize_serial, parse_sn_datetime


class DuplicateCICheck(Check):
    check_id = "DUPLICATE_CI"
    title = "Duplicate CIs"
    dimension = Dimension.CORRECTNESS
    description = (
        "Groups CIs that share a normalised serial number, a normalised MAC address, "
        "or the same name within the same class."
    )
    default_severity = Severity.HIGH

    def run(self, ctx: CheckContext) -> CheckResult:
        cis = ctx.active_cis
        cfg = ctx.config
        strategies: list[tuple[str, Callable[[dict[str, Any]], str | None]]] = [
            ("serial_number", lambda ci: normalize_serial(ci.get("serial_number"), cfg.junk_serials)),
            ("mac_address", lambda ci: normalize_mac(ci.get("mac_address"))),
            (
                "name+class",
                lambda ci: (
                    f"{ci.get('sys_class_name')}|{n}"
                    if (n := normalize_name(ci.get("name"), cfg.strip_domain_for_duplicates))
                    else None
                ),
            ),
        ]
        # ci sys_id -> {strategy: (key, [other sys_ids])}
        matches: dict[str, dict[str, Any]] = defaultdict(dict)
        ci_index = {ci["sys_id"]: ci for ci in cis}
        for strategy, key_fn in strategies:
            groups: dict[str, list[str]] = defaultdict(list)
            for ci in cis:
                key = key_fn(ci)
                if key:
                    groups[key].append(ci["sys_id"])
            for key, members in groups.items():
                if len(members) < 2:
                    continue
                for sys_id in members:
                    matches[sys_id][strategy] = {
                        "key": key,
                        "duplicates_of": sorted(m for m in members if m != sys_id),
                    }
        findings = [
            self.finding(
                ci_index[sys_id],
                f"Possible duplicate matched on {', '.join(sorted(by))}",
                matched_on=by,
            )
            for sys_id, by in sorted(matches.items())
        ]
        return self.result(len(cis), findings)


class OrphanCICheck(Check):
    check_id = "ORPHAN_CI"
    title = "Orphan CIs"
    dimension = Dimension.CORRECTNESS
    description = "CIs that have no upstream or downstream relationship in cmdb_rel_ci."

    def run(self, ctx: CheckContext) -> CheckResult:
        related: set[str] = set()
        for rel in ctx.dataset.relationships:
            related.add(rel.parent)
            related.add(rel.child)
        exempt = ctx.config.orphan_exempt_classes
        in_scope = [
            ci
            for ci in ctx.active_cis
            if not any(ctx.config.is_a(str(ci.get("sys_class_name", "")), e) for e in exempt)
        ]
        findings = [self.finding(ci, "CI has no relationships") for ci in in_scope if ci["sys_id"] not in related]
        return self.result(len(in_scope), findings)


class StaleCICheck(Check):
    check_id = "STALE_CI"
    title = "Stale CIs"
    dimension = Dimension.CORRECTNESS
    description = "Discoverable CIs whose last_discovered is older than stale_days, or never discovered."

    def run(self, ctx: CheckContext) -> CheckResult:
        cfg = ctx.config
        in_scope = [
            ci
            for ci in ctx.active_cis
            if any(cfg.is_a(str(ci.get("sys_class_name", "")), c) for c in cfg.stale_check_classes)
        ]
        findings: list[Finding] = []
        for ci in in_scope:
            last = parse_sn_datetime(ci.get("last_discovered"))
            if last is None:
                findings.append(self.finding(ci, "CI has never been discovered", Severity.HIGH))
                continue
            age = (ctx.as_of - last).days
            if age > cfg.stale_days:
                findings.append(
                    self.finding(
                        ci,
                        f"Last discovered {age} days ago (threshold {cfg.stale_days})",
                        days_since_discovery=age,
                        last_discovered=ci.get("last_discovered"),
                    )
                )
        return self.result(len(in_scope), findings)


class IdentificationRuleCheck(Check):
    check_id = "IDENTIFICATION_RULE"
    title = "Identification rule simulation"
    dimension = Dimension.CORRECTNESS
    description = (
        "Simulates IRE identifier entries in priority order. Flags CIs no entry can identify "
        "and CIs that only match a weak (fallback) entry such as name."
    )

    def run(self, ctx: CheckContext) -> CheckResult:
        cfg = ctx.config
        evaluated = 0
        findings: list[Finding] = []
        for ci in ctx.active_cis:
            cls = str(ci.get("sys_class_name", ""))
            rule = cfg.identification_rule_for(cls)
            if rule is None:
                continue
            evaluated += 1
            rule_class, entries = rule
            matched = None
            for priority, entry in enumerate(entries, start=1):
                if all(not self._missing(ci, attr, cfg) for attr in entry["attributes"]):
                    matched = (priority, entry)
                    break
            if matched is None:
                findings.append(
                    self.finding(
                        ci,
                        f"No identifier entry of rule '{rule_class}' can be satisfied; "
                        "IRE would reject or insert a new CI",
                        Severity.HIGH,
                        rule_class=rule_class,
                    )
                )
            elif not matched[1].get("strong", True):
                findings.append(
                    self.finding(
                        ci,
                        f"Identified only by weak entry {matched[1]['attributes']} (priority {matched[0]})",
                        Severity.LOW,
                        rule_class=rule_class,
                        matched_entry=matched[1]["attributes"],
                        priority=matched[0],
                    )
                )
        return self.result(evaluated, findings)

    @staticmethod
    def _missing(ci: dict[str, Any], attr: str, cfg: Any) -> bool:
        value = ci.get(attr)
        if attr == "serial_number":
            return normalize_serial(value, cfg.junk_serials) is None
        if attr == "mac_address":
            return normalize_mac(value) is None
        return is_blank(value)
