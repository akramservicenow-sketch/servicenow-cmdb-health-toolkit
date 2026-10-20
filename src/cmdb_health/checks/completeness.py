"""Completeness checks: required attributes per class."""

from __future__ import annotations

from cmdb_health.checks.base import Check, CheckContext
from cmdb_health.models import CheckResult, Dimension, Finding, Severity
from cmdb_health.normalize import is_blank, normalize_serial


class MandatoryAttributesCheck(Check):
    check_id = "MISSING_MANDATORY"
    title = "Missing mandatory attributes"
    dimension = Dimension.COMPLETENESS
    description = (
        "Required attributes are resolved up the class hierarchy (e.g. a Linux server inherits "
        "hardware and computer requirements). Placeholder serial numbers count as missing."
    )

    def run(self, ctx: CheckContext) -> CheckResult:
        cfg = ctx.config
        findings: list[Finding] = []
        cis = ctx.active_cis
        for ci in cis:
            required = cfg.mandatory_for(str(ci.get("sys_class_name", "")))
            missing = []
            for attr in required:
                value = ci.get(attr)
                if attr == "serial_number":
                    if normalize_serial(value, cfg.junk_serials) is None:
                        missing.append(attr)
                elif is_blank(value):
                    missing.append(attr)
            if missing:
                severity = Severity.HIGH if len(missing) >= 3 else Severity.MEDIUM
                findings.append(
                    self.finding(ci, f"Missing: {', '.join(missing)}", severity, missing_attributes=missing)
                )
        return self.result(len(cis), findings)
