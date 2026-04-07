"""
preflight_audit.py
------------------
READ-ONLY pre-flight audit for the 1M Bluesky capture run.
Does not write, modify, or delete anything.

Usage:
    python preflight_audit.py
    python preflight_audit.py --db path/to/your.db
    python preflight_audit.py --db path/to/your.db --data-dir path/to/gzip/output

Outputs a structured report to stdout and writes preflight_report.txt
alongside this script.
"""

import argparse
import json
import os
import sqlite3
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Config defaults (override via CLI args) ───────────────────────────────────
DEFAULT_DB_PATH = "bluesky_pipeline.db"   # adjust to match your actual db filename
DEFAULT_DATA_DIR = "data/raw"              # adjust to match where gzip JSONLs land
MATURITY_HOURS = 24                        # minimum hours before a post is hydration-eligible
TARGET_RUN_SIZE = 1_000_000               # posts you intend to capture

# ── Columns the audit expects to find indexes on ─────────────────────────────
EXPECTED_INDEXED_COLUMNS = {
    "posts": ["uri", "did", "captured_at"],
    "hydration_state": ["uri", "hydrated", "hydration_claimed", "captured_at"],
    "actor_enrichment": ["did"],
}

# ── Tables the audit expects to exist ────────────────────────────────────────
EXPECTED_TABLES = [
    "posts",
    "hydration_state",
    "actor_enrichment",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def separator(char="─", width=70):
    return char * width


def section(title):
    lines = [
        "",
        separator("═"),
        f"  {title}",
        separator("═"),
    ]
    return "\n".join(lines)


def ok(msg):    return f"  ✅  {msg}"
def warn(msg):  return f"  ⚠️   {msg}"
def fail(msg):  return f"  ❌  {msg}"
def info(msg):  return f"  ℹ️   {msg}"


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ─────────────────────────────────────────────────────────────────────────────
# Audit functions
# ─────────────────────────────────────────────────────────────────────────────

def audit_db_file(db_path: Path) -> list[str]:
    lines = [section("1. DATABASE FILE")]
    if not db_path.exists():
        lines.append(fail(f"Database not found at: {db_path}"))
        lines.append(warn("Update DEFAULT_DB_PATH at the top of this script or pass --db"))
        return lines

    size = db_path.stat().st_size
    lines.append(ok(f"Database found: {db_path}"))
    lines.append(info(f"File size: {human_bytes(size)}"))

    # Project size at 1M rows based on current size / current row count (done later)
    return lines


def audit_wal_mode(conn) -> list[str]:
    lines = [section("2. WAL MODE (write-ahead logging)")]
    row = conn.execute("PRAGMA journal_mode;").fetchone()
    mode = row[0] if row else "unknown"
    if mode == "wal":
        lines.append(ok(f"Journal mode is WAL — good for concurrent writers"))
    else:
        lines.append(fail(f"Journal mode is '{mode}' — should be WAL for pipeline workloads"))
        lines.append(warn("Fix: conn.execute(\"PRAGMA journal_mode=WAL;\") once before starting capture"))
    return lines


def audit_tables(conn) -> tuple[list[str], list[str]]:
    """Returns (report_lines, found_tables)"""
    lines = [section("3. SCHEMA — TABLE EXISTENCE")]
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ).fetchall()
    found = [r[0] for r in result]
    lines.append(info(f"Tables found: {found}"))

    missing = []
    for t in EXPECTED_TABLES:
        if t in found:
            lines.append(ok(f"Table exists: {t}"))
        else:
            lines.append(fail(f"Table MISSING: {t}"))
            missing.append(t)

    if missing:
        lines.append(warn(f"Missing tables will cause pipeline failures: {missing}"))

    return lines, found


def audit_indexes(conn, found_tables: list[str]) -> list[str]:
    lines = [section("4. INDEXES")]

    all_indexes = conn.execute(
        "SELECT tbl_name, name, sql FROM sqlite_master WHERE type='index';"
    ).fetchall()

    # Build a map: table -> list of indexed column names (best-effort parse)
    indexed: dict[str, list[str]] = {}
    for tbl, idx_name, sql in all_indexes:
        if sql is None:
            continue  # auto index
        if tbl not in indexed:
            indexed[tbl] = []
        # Extract columns from CREATE INDEX ... ON tbl (col1, col2)
        try:
            cols_part = sql[sql.index("(") + 1 : sql.rindex(")")]
            cols = [c.strip().strip('"').split()[0] for c in cols_part.split(",")]
            indexed[tbl].extend(cols)
        except (ValueError, IndexError):
            pass

    for table, expected_cols in EXPECTED_INDEXED_COLUMNS.items():
        if table not in found_tables:
            lines.append(warn(f"Skipping index check for missing table: {table}"))
            continue
        table_indexed = indexed.get(table, [])
        for col in expected_cols:
            if col in table_indexed:
                lines.append(ok(f"{table}.{col} — indexed"))
            else:
                lines.append(warn(f"{table}.{col} — NO index found"))
                lines.append(info(f"    Fix: CREATE INDEX IF NOT EXISTS idx_{table}_{col} ON {table}({col});"))

    return lines


def audit_row_counts(conn, db_path: Path, found_tables: list[str]) -> list[str]:
    lines = [section("5. ROW COUNTS & SCALE PROJECTION")]

    total_posts = 0
    for table in found_tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM \"{table}\";").fetchone()[0]
            lines.append(info(f"{table}: {count:,} rows"))
            if table == "posts":
                total_posts = count
        except Exception as e:
            lines.append(warn(f"Could not count {table}: {e}"))

    if total_posts > 0:
        db_size = db_path.stat().st_size
        bytes_per_post = db_size / total_posts
        projected_size = bytes_per_post * TARGET_RUN_SIZE
        lines.append("")
        lines.append(info(f"Current posts in DB: {total_posts:,}"))
        lines.append(info(f"Estimated bytes/post in DB: {bytes_per_post:.0f} B"))
        lines.append(info(f"Projected DB size at {TARGET_RUN_SIZE:,} posts: {human_bytes(projected_size)}"))

        if projected_size > 5 * 1024 ** 3:
            lines.append(warn("Projected DB > 5 GB — confirm you have disk headroom"))
        else:
            lines.append(ok("Projected DB size looks manageable"))
    else:
        lines.append(warn("No posts found — cannot project scale"))

    return lines


def audit_data_dir(data_dir: Path) -> list[str]:
    lines = [section("6. GZIP JSONL OUTPUT FILES")]

    if not data_dir.exists():
        lines.append(warn(f"Data directory not found: {data_dir}"))
        lines.append(info("Update DEFAULT_DATA_DIR at the top of this script or pass --data-dir"))
        return lines

    gz_files = list(data_dir.rglob("*.jsonl.gz")) + list(data_dir.rglob("*.gz"))
    if not gz_files:
        lines.append(warn(f"No .gz files found in {data_dir}"))
        return lines

    total_size = sum(f.stat().st_size for f in gz_files)
    lines.append(ok(f"Found {len(gz_files)} gzip file(s) in {data_dir}"))
    lines.append(info(f"Total compressed size: {human_bytes(total_size)}"))

    # Estimate raw size (gzip is typically 5-10x compression on JSONL text)
    lines.append(info(f"Estimated uncompressed: ~{human_bytes(total_size * 7)} (assuming ~7x compression)"))

    # Project 1M scale from current file count + size
    # Try to count total lines (posts) across gzip files using wc approach
    import gzip
    sample_files = gz_files[:3]  # Only sample first 3 to avoid reading everything
    sampled_lines = 0
    sampled_bytes = 0
    for f in sample_files:
        try:
            with gzip.open(f, "rb") as fh:
                content = fh.read()
                sampled_lines += content.count(b"\n")
                sampled_bytes += len(f.read_bytes())  # compressed size
        except Exception as e:
            lines.append(warn(f"Could not read {f.name}: {e}"))

    if sampled_lines > 0 and sampled_bytes > 0:
        bytes_per_line = sampled_bytes / sampled_lines
        projected_files_size = bytes_per_line * TARGET_RUN_SIZE
        lines.append(info(f"Sampled {sampled_lines:,} posts across {len(sample_files)} files"))
        lines.append(info(f"Projected compressed file size at 1M posts: {human_bytes(projected_files_size)}"))

    # Check available disk space
    try:
        stat = os.statvfs(data_dir)
        free_bytes = stat.f_bavail * stat.f_frsize
        lines.append(info(f"Free disk space on volume: {human_bytes(free_bytes)}"))
        if free_bytes < 10 * 1024 ** 3:
            lines.append(fail(f"Less than 10 GB free — risky for a 1M run"))
        else:
            lines.append(ok(f"Disk space looks sufficient"))
    except AttributeError:
        # Windows fallback
        import shutil
        free_bytes = shutil.disk_usage(data_dir).free
        lines.append(info(f"Free disk space on volume: {human_bytes(free_bytes)}"))

    return lines


def audit_hydration_timing_gate(conn, found_tables: list[str]) -> list[str]:
    lines = [section("7. HYDRATION TIMING GATE")]

    if "hydration_state" not in found_tables and "posts" not in found_tables:
        lines.append(warn("Neither hydration_state nor posts table found — skipping"))
        return lines

    # Check how many posts exist that are already mature (> 24h old)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MATURITY_HOURS)
    cutoff_str = cutoff.isoformat()

    # Try both common timestamp column names
    for table, col in [("hydration_state", "captured_at"), ("posts", "captured_at"), ("posts", "created_at")]:
        if table not in found_tables:
            continue
        try:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{table}');").fetchall()]
            if col not in cols:
                continue

            total = conn.execute(f"SELECT COUNT(*) FROM \"{table}\";").fetchone()[0]
            mature = conn.execute(
                f"SELECT COUNT(*) FROM \"{table}\" WHERE \"{col}\" < ?;",
                (cutoff_str,)
            ).fetchone()[0]
            immature = total - mature

            lines.append(info(f"Checked '{table}.{col}' for maturity (>{MATURITY_HOURS}h old)"))
            lines.append(info(f"  Total rows: {total:,}"))
            lines.append(ok(f"  Mature (ready to hydrate): {mature:,}"))

            if immature > 0:
                lines.append(warn(f"  Too recent to hydrate yet: {immature:,}"))
                lines.append(info(f"    These posts are < {MATURITY_HOURS}h old and should NOT be hydrated yet"))
            else:
                lines.append(ok(f"  All posts are mature — hydration gate is clear"))

            # Check if hydration_claimed rows exist (TTL-locked)
            if "hydration_claimed" in cols:
                claimed = conn.execute(
                    f"SELECT COUNT(*) FROM \"{table}\" WHERE hydration_claimed = 1 AND hydrated = 0;"
                ).fetchone()[0]
                if claimed > 0:
                    lines.append(warn(f"  {claimed:,} posts are claimed but not yet hydrated (in-flight or stale locks)"))
                    lines.append(info(f"    If a prior hydration run crashed, these may need TTL expiry before resuming"))
                else:
                    lines.append(ok(f"  No stale hydration claims found"))

            break  # found a working table+column, stop
        except Exception as e:
            lines.append(warn(f"Could not query {table}.{col}: {e}"))

    return lines


def audit_deduplication(conn, found_tables: list[str]) -> list[str]:
    lines = [section("8. DEDUPLICATION CHECK")]

    table = "posts"
    if table not in found_tables:
        lines.append(warn("posts table not found — skipping dedup check"))
        return lines

    cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{table}');").fetchall()]
    uri_col = "uri" if "uri" in cols else None

    if not uri_col:
        lines.append(warn("No 'uri' column found in posts — cannot check deduplication"))
        return lines

    try:
        total = conn.execute(f"SELECT COUNT(*) FROM \"{table}\";").fetchone()[0]
        unique = conn.execute(f"SELECT COUNT(DISTINCT {uri_col}) FROM \"{table}\";").fetchone()[0]
        dupes = total - unique

        if dupes == 0:
            lines.append(ok(f"No duplicate URIs found ({total:,} total, {unique:,} unique)"))
        else:
            pct = (dupes / total) * 100
            lines.append(warn(f"{dupes:,} duplicate URIs detected ({pct:.1f}% of rows)"))
            lines.append(info("    The firehose dedup logic may not be catching all duplicates"))
            lines.append(info("    At 1M scale this could waste significant hydration API calls"))
    except Exception as e:
        lines.append(warn(f"Dedup check failed: {e}"))

    return lines


def audit_resume_safety(conn, found_tables: list[str]) -> list[str]:
    lines = [section("9. RESUME / RESTART SAFETY")]

    lines.append(info("Checking whether a mid-run crash would be recoverable..."))

    if "posts" in found_tables:
        cols = [r[1] for r in conn.execute("PRAGMA table_info('posts');").fetchall()]
        has_captured_at = "captured_at" in cols
        has_uri = "uri" in cols

        if has_uri and has_captured_at:
            lines.append(ok("posts table has uri + captured_at — resume anchor exists"))
        else:
            missing = [c for c in ["uri", "captured_at"] if c not in cols]
            lines.append(warn(f"posts table missing columns for resume: {missing}"))

    if "hydration_state" in found_tables:
        cols = [r[1] for r in conn.execute("PRAGMA table_info('hydration_state');").fetchall()]
        needed = ["uri", "hydrated", "hydration_claimed"]
        missing = [c for c in needed if c not in cols]
        if not missing:
            lines.append(ok("hydration_state has all needed columns for resume (uri, hydrated, hydration_claimed)"))
        else:
            lines.append(warn(f"hydration_state missing resume columns: {missing}"))
    else:
        lines.append(warn("No hydration_state table — hydration resume safety cannot be confirmed"))

    lines.append(info("Manual check recommended: run capture → kill it → restart → confirm no duplicate URIs added"))

    return lines


def summary(all_lines: list[str]) -> list[str]:
    warnings = sum(1 for l in all_lines if "⚠️" in l)
    failures = sum(1 for l in all_lines if "❌" in l)
    lines = [
        section("SUMMARY"),
        info(f"Failures (must fix before 1M run): {failures}"),
        info(f"Warnings (should review):          {warnings}"),
        "",
    ]
    if failures == 0 and warnings == 0:
        lines.append(ok("All checks passed — system looks ready for the 1M run"))
    elif failures == 0:
        lines.append(warn("No hard failures, but review warnings above before starting"))
    else:
        lines.append(fail(f"{failures} failure(s) found — resolve these before starting the 1M run"))

    lines.append("")
    lines.append(info(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Read-only pre-flight audit for 1M Bluesky run")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Path to gzip JSONL output directory")
    args = parser.parse_args()

    db_path = Path(args.db)
    data_dir = Path(args.data_dir)

    all_lines = [
        "=" * 70,
        "  BLUESKY 1M RUN — PRE-FLIGHT AUDIT REPORT",
        "  Read-only. Nothing was modified.",
        "=" * 70,
    ]

    # DB file check
    all_lines += audit_db_file(db_path)

    if not db_path.exists():
        all_lines += [
            "",
            fail("Cannot continue audit — database file not found."),
            info("Run with --db to point to your actual database path."),
        ]
        report = "\n".join(all_lines)
        print(report)
        return

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)  # read-only connection
    conn.row_factory = sqlite3.Row

    try:
        all_lines += audit_wal_mode(conn)
        table_lines, found_tables = audit_tables(conn)
        all_lines += table_lines
        all_lines += audit_indexes(conn, found_tables)
        all_lines += audit_row_counts(conn, db_path, found_tables)
        all_lines += audit_data_dir(data_dir)
        all_lines += audit_hydration_timing_gate(conn, found_tables)
        all_lines += audit_deduplication(conn, found_tables)
        all_lines += audit_resume_safety(conn, found_tables)
        all_lines += summary(all_lines)
    finally:
        conn.close()

    report = "\n".join(all_lines)
    print(report)

    # Write to file alongside the script
    out_path = Path(__file__).parent / "preflight_report.txt"
    out_path.write_text(report)
    print(f"\n  Report saved to: {out_path}")


if __name__ == "__main__":
    main()