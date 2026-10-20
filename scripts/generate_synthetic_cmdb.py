#!/usr/bin/env python3
"""Generate a synthetic CMDB export with deliberately injected data-quality issues.

Everything produced here is fake: names use the reserved ``example.internal``
domain, IPs are RFC 1918, MACs are locally administered (02:...), and owners
are opaque placeholder ids. Output is deterministic for a given --seed.

    python scripts/generate_synthetic_cmdb.py --count 80 --out sample_data
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

VENDORS = ["Synthetic Vendor A", "Synthetic Vendor B", "Synthetic Vendor C"]
OSES = ["Linux Red Hat", "Linux Ubuntu", "Windows 2022 Datacenter"]
LOCATIONS = ["DC-East-01", "DC-West-02", "Colo-Central-03"]
GROUPS = ["grp-linux-ops", "grp-windows-ops", "grp-network-eng", "grp-app-support", "grp-dba"]
APPS = ["billing-api", "orders-web", "inventory-svc", "auth-gateway", "reporting-etl", "search-index"]
DOMAIN = "example.internal"


class Generator:
    def __init__(self, seed: int, as_of: datetime) -> None:
        self.rng = random.Random(seed)
        self.as_of = as_of
        self.cis: list[dict[str, Any]] = []
        self.rels: list[dict[str, Any]] = []

    # -- primitives ---------------------------------------------------------------
    def sys_id(self) -> str:
        return f"{self.rng.getrandbits(128):032x}"

    def mac(self) -> str:
        octets = [0x02] + [self.rng.randint(0, 255) for _ in range(5)]
        return ":".join(f"{o:02X}" for o in octets)

    def serial(self) -> str:
        return "SYN" + "".join(self.rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(9))

    def discovered(self, max_age_days: int = 7) -> str:
        ts = self.as_of - timedelta(days=self.rng.randint(0, max_age_days), hours=self.rng.randint(0, 23))
        return ts.strftime("%Y-%m-%d %H:%M:%S")

    def owner(self) -> str:
        return f"user-{self.rng.randint(1, 400):04d}"

    def base(self, cls: str, name: str) -> dict[str, Any]:
        return {
            "sys_id": self.sys_id(),
            "name": name,
            "sys_class_name": cls,
            "operational_status": "1",
            "install_status": "1",
            "support_group": self.rng.choice(GROUPS),
            "owned_by": self.owner(),
            "discovery_source": "ServiceNow",
            "last_discovered": self.discovered(),
        }

    def hardware(self, cls: str, name: str) -> dict[str, Any]:
        ci = self.base(cls, name)
        ci.update(
            serial_number=self.serial(),
            mac_address=self.mac(),
            manufacturer=self.rng.choice(VENDORS),
            model_id=f"model-{self.rng.randint(100, 999)}",
            location=self.rng.choice(LOCATIONS),
            fqdn=f"{name}.{DOMAIN}",
        )
        return ci

    def rel(self, parent: dict[str, Any], child: dict[str, Any] | str, rel_type: str) -> None:
        child_id = child if isinstance(child, str) else child["sys_id"]
        self.rels.append({"sys_id": self.sys_id(), "parent": parent["sys_id"], "child": child_id, "type": rel_type})

    # -- build --------------------------------------------------------------------
    def build(self, count: int) -> None:
        n_services = max(2, count // 15)
        n_apps = max(3, count // 5)
        n_servers = max(4, count // 3)
        n_switches = max(2, count // 15)
        n_vms = max(2, count - n_services - n_apps - n_servers - n_switches)

        servers = []
        for i in range(1, n_servers + 1):
            cls = "cmdb_ci_linux_server" if i % 3 else "cmdb_ci_win_server"
            ci = self.hardware(cls, f"srv{'lx' if i % 3 else 'win'}{i:03d}")
            ci.update(os=OSES[2] if cls == "cmdb_ci_win_server" else self.rng.choice(OSES[:2]))
            ci["ip_address"] = f"10.20.{i // 250}.{i % 250 + 1}"
            servers.append(ci)
        switches = []
        for i in range(1, n_switches + 1):
            switches.append(self.hardware("cmdb_ci_ip_switch", f"sw-core-{i:02d}"))
        vms = []
        for i in range(1, n_vms + 1):
            ci = self.base("cmdb_ci_vm_instance", f"vm{i:03d}")
            ci.update(object_id=f"vm-{self.rng.getrandbits(32):08x}", ip_address=f"10.30.{i // 250}.{i % 250 + 1}")
            vms.append(ci)
        apps = []
        for i in range(1, n_apps + 1):
            ci = self.base("cmdb_ci_appl", f"{APPS[i % len(APPS)]}-{i:02d}")
            ci.update(version=f"{self.rng.randint(1, 5)}.{self.rng.randint(0, 9)}.{self.rng.randint(0, 20)}")
            ci["discovery_source"] = "Service Mapping"
            apps.append(ci)
        services = []
        for i in range(1, n_services + 1):
            ci = self.base("cmdb_ci_service_discovered", f"Business App Service {i:02d}")
            ci.update(service_classification="Application Service", discovery_source="Manual")
            ci.pop("last_discovered")
            services.append(ci)

        # healthy relationships
        for vm in vms:
            self.rel(vm, self.rng.choice(servers), "Virtualized by::Virtualizes")
        for app in apps:
            host = self.rng.choice(servers + vms)
            self.rel(app, host, "Runs on::Runs")
        for svc in services:
            for app in self.rng.sample(apps, k=min(3, len(apps))):
                self.rel(svc, app, "Depends on::Used by")
        for sw in switches:
            for srv in self.rng.sample(servers, k=min(3, len(servers))):
                self.rel(sw, srv, "Connects to::Connected by")

        self.cis = servers + switches + vms + apps + services
        self.inject_issues(servers, vms, apps)

    def inject_issues(self, servers: list[dict], vms: list[dict], apps: list[dict]) -> None:
        rng = self.rng
        # Duplicates: same serial with different formatting, same MAC in Cisco
        # dotted notation, and the same host loaded once as FQDN and once short.
        a, b = servers[1], servers[2]
        b["serial_number"] = "-".join([a["serial_number"][:4], a["serial_number"][4:]]).lower()
        c, d = servers[3], servers[4]
        raw = c["mac_address"].replace(":", "").lower()
        d["mac_address"] = f"{raw[0:4]}.{raw[4:8]}.{raw[8:12]}"
        dup = dict(servers[5])
        dup.update(
            sys_id=self.sys_id(),
            name=f"{servers[5]['name']}.{DOMAIN}",
            serial_number=self.serial(),
            mac_address=self.mac(),
            discovery_source="Manual Entry",
        )
        self.cis.append(dup)

        # Missing mandatory attributes / placeholder serials.
        servers[6]["serial_number"] = "To Be Filled By O.E.M."
        servers[7]["os"] = ""
        servers[7]["location"] = ""
        servers[8].update(manufacturer="", model_id="", location="", ip_address="")
        apps[1]["version"] = ""

        # Stale and never discovered.
        servers[9]["last_discovered"] = (self.as_of - timedelta(days=95)).strftime("%Y-%m-%d %H:%M:%S")
        vms[0]["last_discovered"] = (self.as_of - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
        servers[10]["last_discovered"] = ""

        # Unowned.
        for ci in (servers[11], apps[2], vms[1]):
            ci["support_group"] = ""
            ci["owned_by"] = ""

        # Weak or impossible identification.
        vms[1]["object_id"] = ""
        servers[6]["mac_address"] = "00:00:00:00:00:00"
        servers[6]["name"] = ""

        # Orphans: a manually created server and an app with no relationships.
        orphan = self.hardware("cmdb_ci_linux_server", "srvlx-legacy-01")
        orphan.update(os="Linux Red Hat", ip_address="10.20.9.9", discovery_source="Manual Entry")
        orphan_app = self.base("cmdb_ci_appl", "legacy-batch-01")
        orphan_app.update(version="0.9.1", discovery_source="Manual Entry")
        self.cis += [orphan, orphan_app]

        # Invalid relationships.
        self.rel(apps[3], servers[12], "Owns::Owned by")  # not on the allow-list
        self.rel(apps[4], servers[13], "Depends on::Used by")  # allowed, but wrong for app->server
        self.rel(apps[5], self.sys_id(), "Runs on::Runs")  # dangling child

        # A retired CI that should be excluded from scope.
        retired = self.hardware("cmdb_ci_linux_server", "srvlx-retired-01")
        retired.update(
            install_status="7",
            operational_status="6",
            os="Linux Red Hat",
            support_group="",
            owned_by="",
            last_discovered="2023-01-01 00:00:00",
            ip_address="10.20.9.10",
        )
        self.cis.append(retired)
        rng.shuffle(self.cis)


def write_outputs(gen: Generator, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "cis.json").write_text(json.dumps({"result": gen.cis}, indent=2) + "\n", encoding="utf-8")
    (out / "relationships.json").write_text(json.dumps({"result": gen.rels}, indent=2) + "\n", encoding="utf-8")
    columns = sorted({k for ci in gen.cis for k in ci})
    with (out / "cis.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for ci in gen.cis:
            writer.writerow({c: ci.get(c, "") for c in columns})
    with (out / "relationships.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["sys_id", "parent", "child", "type"])
        writer.writeheader()
        writer.writerows(gen.rels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=60, help="approximate number of healthy CIs (min 45)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", default="2026-10-01", help="reference date used for discovery timestamps")
    parser.add_argument("--out", type=Path, default=Path("sample_data"))
    args = parser.parse_args(argv)
    if args.count < 45:
        parser.error("--count must be at least 45 so every injected issue has a target")
    as_of = datetime.fromisoformat(args.as_of).replace(tzinfo=UTC)
    gen = Generator(args.seed, as_of)
    gen.build(args.count)
    write_outputs(gen, args.out)
    print(f"wrote {len(gen.cis)} CIs and {len(gen.rels)} relationships to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
