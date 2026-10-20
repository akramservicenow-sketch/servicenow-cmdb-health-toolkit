"""Command-line interface: ``cmdb-health``."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from cmdb_health import __version__
from cmdb_health.checks import ALL_CHECKS
from cmdb_health.config import load_config
from cmdb_health.engine import run_health_checks
from cmdb_health.models import Dataset
from cmdb_health.reports import render_console, write_csv, write_html, write_json
from cmdb_health.sources.local import DataSourceError, load_local

FORMATS = ("console", "json", "csv", "html")
DEFAULT_TABLES = "cmdb_ci_server,cmdb_ci_vm_instance,cmdb_ci_netgear,cmdb_ci_appl,cmdb_ci_service"


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date '{value}' (use YYYY-MM-DD)") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_formats(value: str) -> list[str]:
    formats = [v.strip().lower() for v in value.split(",") if v.strip()]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown format(s): {', '.join(bad)}; choose from {', '.join(FORMATS)}")
    return formats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cmdb-health",
        description="Evaluate ServiceNow CMDB data quality (completeness, correctness, compliance).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="run health checks and write reports")
    scan.add_argument("--source", choices=["local", "servicenow"], default="local")
    scan.add_argument("--cis", type=Path, help="CI export (.json or .csv); JSON may bundle relationships")
    scan.add_argument("--relationships", type=Path, help="cmdb_rel_ci export (.json or .csv)")
    scan.add_argument("--tables", default=DEFAULT_TABLES, help="comma-separated CI tables (servicenow source)")
    scan.add_argument("--query", default="install_status!=7", help="encoded query applied to CI tables")
    scan.add_argument("--max-records", type=int, help="cap records per table (servicenow source)")
    scan.add_argument("--config", type=Path, help="TOML file overriding default rules")
    scan.add_argument("--as-of", type=_parse_as_of, help="reference date for staleness (default: now, UTC)")
    scan.add_argument("--format", type=_parse_formats, default=["console"], help="console,json,csv,html")
    scan.add_argument("--output-dir", type=Path, default=Path("reports"))
    scan.add_argument("--top", type=int, default=10, help="findings to print in the console summary")
    scan.add_argument("--fail-under", type=float, help="exit 2 if the overall score is below this value")
    scan.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("checks", help="list available checks")
    return parser


def _load_dataset(args: argparse.Namespace) -> tuple[Dataset, str]:
    if args.source == "local":
        if not args.cis:
            raise DataSourceError("--cis is required for the local source")
        return load_local(args.cis, args.relationships), f"local:{args.cis.name}"

    from cmdb_health.sources.servicenow import ServiceNowClient, ServiceNowSettings

    settings = ServiceNowSettings.from_env()
    tables = [t.strip() for t in args.tables.split(",") if t.strip()]
    client = ServiceNowClient(settings)
    dataset = client.fetch_dataset(tables, args.query or None, max_records=args.max_records)
    return dataset, f"servicenow:{settings.instance_url}"


def cmd_checks() -> int:
    print(f"{'ID':<22} {'Dimension':<13} Description")
    for cls in ALL_CHECKS:
        print(f"{cls.check_id:<22} {cls.dimension.value:<13} {cls.description}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    dataset, source = _load_dataset(args)
    report = run_health_checks(dataset, config, as_of=args.as_of, source=source)

    if "console" in args.format:
        sys.stdout.write(render_console(report, args.top))
    file_formats = [f for f in args.format if f != "console"]
    if file_formats:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        writers = {
            "json": (write_json, "cmdb_health.json"),
            "csv": (write_csv, "cmdb_health_findings.csv"),
            "html": (write_html, "cmdb_health.html"),
        }
        for fmt in file_formats:
            writer, filename = writers[fmt]
            path = writer(report, args.output_dir / filename)
            print(f"wrote {path}", file=sys.stderr)

    if args.fail_under is not None and report.overall_score < args.fail_under:
        print(f"overall score {report.overall_score} is below --fail-under {args.fail_under}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "checks":
        return cmd_checks()
    try:
        return cmd_scan(args)
    except (DataSourceError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:  # ServiceNowError and friends
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
