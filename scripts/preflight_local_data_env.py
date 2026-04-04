#!/usr/bin/env python3
"""Local import preflight checks (import-only, no Snowflake connections)."""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import datetime, timezone
from importlib import metadata
from typing import Any

REQUIRED_MODULES: tuple[str, ...] = ("pandas", "pyarrow", "snowflake.connector")
PACKAGE_BY_MODULE: dict[str, str] = {
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "snowflake.connector": "snowflake-connector-python",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local import readiness for parquet/data tooling."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output (default prints concise summary).",
    )
    return parser


def run_preflight(module_names: tuple[str, ...] = REQUIRED_MODULES) -> dict[str, Any]:
    """Return import availability/version checks for required modules."""

    imports: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    for module_name in module_names:
        result: dict[str, Any] = {"available": False, "version": None, "error": None}
        try:
            module = importlib.import_module(module_name)
            result["available"] = True
            package_name = PACKAGE_BY_MODULE.get(module_name, module_name)
            try:
                result["version"] = metadata.version(package_name)
            except Exception:
                result["version"] = getattr(module, "__version__", None)
        except Exception as exc:  # pragma: no cover - defensive
            result["error"] = f"{type(exc).__name__}: {exc}"
            failures.append(f"import_failed:{module_name}")

        imports[module_name] = result

    status = "pass" if not failures else "fail"
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "imports": imports,
        "status": status,
        "failures": failures,
        "overall_pass": status == "pass",
    }


def _print_concise_summary(report: dict[str, Any]) -> None:
    print("Local data environment preflight")
    for module_name in REQUIRED_MODULES:
        result = report["imports"][module_name]
        marker = "PASS" if result["available"] else "FAIL"
        version = f" version={result['version']}" if result["version"] else ""
        error = f" error={result['error']}" if result["error"] else ""
        print(f"- {module_name}: {marker}{version}{error}")
    print(f"status={report['status']}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_preflight()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_concise_summary(report)
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
