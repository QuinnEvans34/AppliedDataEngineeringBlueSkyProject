#!/usr/bin/env python3
"""Render sql/00_setup/04_udfs_template.sql -> sql/00_setup/_generated/03_udfs.rendered.sql.

Modes:
  --terms-json PATH   read terms + whitelist from a local JSON file (default/CI)
  --from-snowflake    pull from ENHANCED.PROFANITY_TERMS/PROFANITY_WHITELIST.
                      Requires env vars SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
                      SNOWFLAKE_PASSWORD, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE.

Template placeholders: {{PROFANITY_TERMS_JSON}}, {{PROFANITY_WHITELIST_JSON}}.
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "sql" / "00_setup" / "04_udfs_template.sql"
OUTPUT_PATH = REPO_ROOT / "sql" / "00_setup" / "_generated" / "03_udfs.rendered.sql"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"
GITIGNORE_ENTRY = "sql/00_setup/_generated/"
GUARD_BEGIN = "-- ---- BEGIN TEMPLATE GUARD ----"
GUARD_END = "-- ---- END TEMPLATE GUARD ----"
PH_TERMS = "{{PROFANITY_TERMS_JSON}}"
PH_WHITELIST = "{{PROFANITY_WHITELIST_JSON}}"
SF_ENV = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
          "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE"]


def load_from_json(path: Path):
    if not path.exists():
        sys.exit(f"--terms-json path does not exist: {path}")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or "terms" not in data or "whitelist" not in data:
        sys.exit("--terms-json file must be a JSON object with 'terms' and 'whitelist'")
    terms = [{"term": str(r["term"]), "severity": str(r["severity"]),
              "allow_separators": bool(r.get("allow_separators", False))}
             for r in data["terms"]]
    whitelist = [str(w).lower() for w in data["whitelist"]]
    return terms, whitelist


def load_from_snowflake():
    missing = [v for v in SF_ENV if not os.environ.get(v)]
    if missing:
        sys.exit(f"--from-snowflake missing env vars: {', '.join(missing)}. "
                 f"Use --terms-json <path> for offline rendering instead.")
    try:
        import snowflake.connector  # type: ignore
    except ImportError:
        sys.exit("snowflake-connector-python not installed; use --terms-json instead.")
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"], schema="ENHANCED")
    try:
        cur = conn.cursor()
        cur.execute("SELECT term, severity, allow_separators "
                    "FROM ENHANCED.PROFANITY_TERMS ORDER BY term")
        terms = [{"term": r[0], "severity": r[1], "allow_separators": bool(r[2])}
                 for r in cur.fetchall()]
        cur.execute("SELECT term FROM ENHANCED.PROFANITY_WHITELIST ORDER BY term")
        whitelist = [r[0].lower() for r in cur.fetchall()]
    finally:
        conn.close()
    return terms, whitelist


def strip_guard(text: str) -> str:
    b = text.find(GUARD_BEGIN)
    e = text.find(GUARD_END)
    if b == -1 or e == -1 or e < b:
        return text
    line_end = text.find("\n", e)
    line_end = len(text) if line_end == -1 else line_end + 1
    return text[:b] + text[line_end:]


def render(terms, whitelist, template: str) -> str:
    if PH_TERMS not in template:
        sys.exit(f"template missing placeholder {PH_TERMS}")
    if PH_WHITELIST not in template:
        sys.exit(f"template missing placeholder {PH_WHITELIST}")
    return (strip_guard(template)
            .replace(PH_TERMS, json.dumps(terms, sort_keys=True))
            .replace(PH_WHITELIST, json.dumps(sorted(whitelist))))


def ensure_gitignore() -> None:
    if not GITIGNORE_PATH.exists():
        GITIGNORE_PATH.write_text(GITIGNORE_ENTRY + "\n")
        return
    contents = GITIGNORE_PATH.read_text()
    if GITIGNORE_ENTRY in contents:
        return
    sep = "" if contents.endswith("\n") else "\n"
    GITIGNORE_PATH.write_text(contents + sep + GITIGNORE_ENTRY + "\n")


def summary(terms, whitelist) -> None:
    print(f"terms_total={len(terms)}")
    print(f"whitelist_total={len(whitelist)}")
    counts = {}
    for t in terms:
        counts[t["severity"]] = counts.get(t["severity"], 0) + 1
    for sev in sorted(counts):
        print(f"  {sev}: {counts[sev]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--terms-json", type=Path, metavar="PATH",
                      help="read terms + whitelist from a local JSON file")
    mode.add_argument("--from-snowflake", action="store_true",
                      help="pull terms + whitelist from Snowflake via env vars")
    ap.add_argument("--dry-run", action="store_true",
                    help="print rendered SQL to stdout instead of writing")
    args = ap.parse_args()
    terms, whitelist = (load_from_json(args.terms_json) if args.terms_json
                        else load_from_snowflake())
    rendered = render(terms, whitelist, TEMPLATE_PATH.read_text())
    summary(terms, whitelist)
    if args.dry_run:
        sys.stdout.write(rendered)
        return
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered)
    ensure_gitignore()
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
