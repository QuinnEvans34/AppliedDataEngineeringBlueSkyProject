"""
Bluesky Pipeline — Live Demo Load Script

Captures 25 live posts from the Bluesky firehose, fetches actor profiles
for their authors, and loads both datasets into Snowflake RAW landing tables.
Designed to run live in front of a professor in 2-3 minutes.

PRE-DEMO CHECKLIST:
  [ ] Virtual environment activated
  [ ] Snowflake credentials in environment or .env
  [ ] RAW schema deployed in Snowflake
  [ ] LANDING_RAW_POSTS table exists
  [ ] LANDING_ACTOR_PROFILES table exists
  [ ] RAW.BLUESKY_RAW_POSTS_STAGE exists
  [ ] RAW.BLUESKY_ACTOR_PROFILES_STAGE exists
  [ ] RAW.BLUESKY_RAW_POSTS_PIPE exists with AUTO_INGEST = TRUE
  [ ] RAW.BLUESKY_ACTOR_PROFILES_PIPE exists with AUTO_INGEST = TRUE
  [ ] ENHANCED.TASK_ENRICH_POSTS is RESUMED
  [ ] ENHANCED.TASK_BUILD_ML_READY is RESUMED
  [ ] Internet connection active
  Run: python scripts/demo/demo_load.py
"""

from __future__ import annotations

import base64
import datetime
import gzip
import json
import os
import ssl
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIREHOSE_URL = "wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos"
PROFILE_API_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles"

TARGET_POST_COUNT = 25

POST_OUTPUT_DIR = Path("data/demo/raw_posts")
ACTOR_OUTPUT_DIR = Path("data/demo/actor_profiles")
POST_FILENAME = "demo_raw_posts.jsonl.gz"
ACTOR_FILENAME = "demo_actor_profiles.jsonl.gz"

POSTS_STAGE = "RAW.BLUESKY_RAW_POSTS_STAGE"
ACTOR_STAGE = "RAW.BLUESKY_ACTOR_PROFILES_STAGE"
POSTS_LANDING_TABLE = "RAW.LANDING_RAW_POSTS"
ACTOR_LANDING_TABLE = "RAW.LANDING_ACTOR_PROFILES"
FILE_FORMAT = "RAW.BLUESKY_JSONL_GZ"

SOURCE_RUN_TAG = "demo_run"
LOAD_INVOCATION_ID = "demo"

# Per-invocation run id used to give each PUT a unique stage subfolder so
# the pipe PATTERN (`^.*/raw_posts/[^/]+/[^/]+\.jsonl\.gz$`) matches.
DEMO_RUN_ID = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

SNOWFLAKE_ENV_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)

# ---------------------------------------------------------------------------
# Helpers — copied from the pipeline so this file stays standalone
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _to_json_safe(value: Any) -> Any:
    """Recursively coerce values into JSON-serializable primitives."""
    if isinstance(value, Mapping):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"$bytes_b64": base64.b64encode(value).decode("ascii")}
    return value


def _to_int_or_none(value: Any) -> int | None:
    """Coerce to int or return None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_ssl_context() -> ssl.SSLContext:
    """Build SSL context with certifi CA bundle when available."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _write_jsonl_gz(path: Path, rows: list[dict]) -> int:
    """Write rows as gzipped JSONL. Returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
    return len(rows)


def _validate_env() -> dict[str, str]:
    """Check that all required Snowflake env vars are set."""
    creds: dict[str, str] = {}
    missing: list[str] = []
    for var in SNOWFLAKE_ENV_VARS:
        val = os.environ.get(var)
        if not val:
            missing.append(var)
        else:
            creds[var] = val
    if missing:
        print(f"\n  ❌ Missing environment variables: {', '.join(missing)}")
        print("  Set them in your shell or .env file before running the demo.")
        sys.exit(1)
    return creds


# ---------------------------------------------------------------------------
# Step 1 + 2: Connect to firehose and capture 25 posts
# ---------------------------------------------------------------------------


def _capture_posts() -> list[dict]:
    """Connect to the Bluesky firehose and capture TARGET_POST_COUNT posts."""

    try:
        from websockets.sync.client import connect
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: websockets")
        print("  Install with: pip install websockets")
        sys.exit(1)

    try:
        from atproto_firehose.client import _get_message_frame_from_bytes_or_raise
        from atproto_firehose import parse_subscribe_repos_message
        from atproto_core.car import CAR
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: atproto")
        print("  Install with: pip install atproto")
        sys.exit(1)

    capture_run_id = str(uuid.uuid4())
    posts: list[dict] = []
    seen_uris: set[str] = set()
    ssl_ctx = _build_ssl_context()

    print("\n[1/5] Connecting to Bluesky firehose...")

    try:
        with connect(
            FIREHOSE_URL,
            ping_interval=None,
            close_timeout=0.1,
            max_size=16 * 1024 * 1024,
            ssl=ssl_ctx,
        ) as ws:
            print(f"      ✅ Connected to {FIREHOSE_URL.split('//')[1].split('/')[0]}")
            print(f"\n[2/5] Capturing {TARGET_POST_COUNT} live posts...")

            while len(posts) < TARGET_POST_COUNT:
                frame = ws.recv(timeout=30.0)
                if not isinstance(frame, bytes):
                    continue

                # Decode frame
                try:
                    message_frame = _get_message_frame_from_bytes_or_raise(frame)
                except Exception:
                    continue

                # Normalize event type
                raw_type = str(message_frame.type).strip().lower() if message_frame.type else ""
                if raw_type not in {"#commit", "commit", "com.atproto.sync.subscriberepos#commit", "1"}:
                    continue

                try:
                    parsed = parse_subscribe_repos_message(message_frame)
                except Exception:
                    continue

                # Get ops list
                ops = getattr(parsed, "ops", None)
                if not isinstance(ops, list):
                    continue

                # Decode CAR blocks
                raw_blocks = getattr(parsed, "blocks", None)
                records_by_cid: dict[Any, Mapping[str, Any]] = {}
                if isinstance(raw_blocks, (bytes, bytearray)):
                    try:
                        car = CAR.from_bytes(bytes(raw_blocks))
                        for cid_obj, record in car.blocks.items():
                            if isinstance(record, Mapping):
                                records_by_cid[cid_obj] = record
                                records_by_cid[str(cid_obj)] = record
                    except Exception:
                        continue

                repo_did = str(getattr(parsed, "repo", "") or "")
                seq = getattr(parsed, "seq", None)
                event_time = getattr(parsed, "time", None)

                for op in ops:
                    if len(posts) >= TARGET_POST_COUNT:
                        break

                    action = str(getattr(op, "action", "") or "")
                    if action != "create":
                        continue

                    path = str(getattr(op, "path", "") or "")
                    if "/" not in path:
                        continue
                    collection, rkey = path.rsplit("/", 1)
                    if collection != "app.bsky.feed.post":
                        continue

                    raw_cid = getattr(op, "cid", None)
                    cid_str = str(raw_cid) if raw_cid is not None else None

                    # Resolve record from CAR blocks
                    record = None
                    if raw_cid is not None:
                        record = records_by_cid.get(raw_cid)
                    if not isinstance(record, Mapping) and cid_str is not None:
                        record = records_by_cid.get(cid_str)
                    if not isinstance(record, Mapping):
                        continue

                    uri = f"at://{repo_did}/{collection}/{rkey}"
                    if uri in seen_uris:
                        continue
                    seen_uris.add(uri)

                    # Build normalized row matching firehose/normalizer.py schema
                    row = {
                        "capture_run_id": capture_run_id,
                        "seq": seq,
                        "repo_did": repo_did,
                        "event_time": event_time,
                        "operation": "create",
                        "collection": collection,
                        "rkey": rkey,
                        "uri": uri,
                        "cid": cid_str,
                        "record_created_at": record.get("createdAt"),
                        "has_reply": record.get("reply") is not None,
                        "has_embed": record.get("embed") is not None,
                        "captured_at": _utc_now_iso(),
                        "record": _to_json_safe(record),
                    }
                    posts.append(row)
                    print(f"      Post {len(posts)}/{TARGET_POST_COUNT} captured: {uri}")

    except Exception as e:
        print(f"\n  ❌ Step failed: {e}")
        print("  Check your internet connection and try again.")
        sys.exit(1)

    print(f"      ✅ {len(posts)} posts captured. Disconnecting from firehose.")

    # Write posts JSONL
    post_path = POST_OUTPUT_DIR / POST_FILENAME
    _write_jsonl_gz(post_path, posts)

    return posts


# ---------------------------------------------------------------------------
# Step 3: Fetch actor profiles
# ---------------------------------------------------------------------------


def _fetch_actor_profiles(posts: list[dict]) -> list[dict]:
    """Fetch actor profiles for the unique DIDs found in captured posts."""

    try:
        import httpx
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: httpx")
        print("  Install with: pip install httpx")
        sys.exit(1)
    try:
        from bluesky_pipeline.actor.normalizer import normalize_actor_profile
    except ModuleNotFoundError:
        # Keep demo script runnable when invoked as `python scripts/demo/demo_load.py`.
        repo_root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo_root))
        from bluesky_pipeline.actor.normalizer import normalize_actor_profile

    # Extract unique DIDs preserving order
    seen: set[str] = set()
    unique_dids: list[str] = []
    for post in posts:
        did = post["repo_did"]
        if did not in seen:
            seen.add(did)
            unique_dids.append(did)

    print(f"\n[3/5] Fetching actor profiles for {len(unique_dids)} authors...")

    actor_run_id = str(uuid.uuid4())

    try:
        params = [("actors", did) for did in unique_dids]
        resp = httpx.get(
            PROFILE_API_URL,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": "bluesky-pipeline-demo/1.0",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        profiles_data = resp.json().get("profiles", [])
    except Exception as e:
        print(f"\n  ❌ Step failed: {e}")
        print("  Check your internet connection and try again.")
        sys.exit(1)

    # Normalize each profile to match actor/normalizer.py schema
    actor_rows: list[dict] = []
    enriched_at = _utc_now_iso()

    for pv in profiles_data:
        actor_rows.append(
            normalize_actor_profile(
                actor_run_id=actor_run_id,
                profile_view=pv,
                enriched_at=enriched_at,
            )
        )

    print(f"      ✅ {len(actor_rows)} actor profiles retrieved")

    # Write actor profiles JSONL
    actor_path = ACTOR_OUTPUT_DIR / ACTOR_FILENAME
    _write_jsonl_gz(actor_path, actor_rows)

    return actor_rows


# ---------------------------------------------------------------------------
# Step 4: Load to Snowflake
# ---------------------------------------------------------------------------


def _load_to_snowflake(
    post_count: int, actor_count: int
) -> tuple[int, int]:
    """PUT files to stages"""

    try:
        import snowflake.connector
    except ModuleNotFoundError:
        print("\n  ❌ Missing dependency: snowflake-connector-python")
        print("  Install with: pip install snowflake-connector-python")
        sys.exit(1)

    creds = _validate_env()

    print("\n[4/5] Loading to Snowflake RAW layer...")

    try:
        conn = snowflake.connector.connect(
            account=creds["SNOWFLAKE_ACCOUNT"],
            user=creds["SNOWFLAKE_USER"],
            password=creds["SNOWFLAKE_PASSWORD"],
            role=creds["SNOWFLAKE_ROLE"],
            warehouse=creds["SNOWFLAKE_WAREHOUSE"],
            database=creds["SNOWFLAKE_DATABASE"],
            schema=creds["SNOWFLAKE_SCHEMA"],
            autocommit=True,
        )
    except Exception as e:
        print(f"\n  ❌ Snowflake connection failed: {e}")
        print("  Check your credentials and network.")
        sys.exit(1)

    cur = conn.cursor()

    try:
        # --- PUT posts to stage (Snowpipe AUTO_INGEST handles the COPY) ---
        # Stage subpath MUST be `<source_run_tag>/raw_posts/<run_id>/` so the
        # pipe PATTERN `^.*/raw_posts/[^/]+/[^/]+\.jsonl\.gz$` matches and so
        # SPLIT_PART(METADATA$FILENAME, '/', 1) yields the source_run_tag.
        post_file = (POST_OUTPUT_DIR / POST_FILENAME).resolve()
        post_stage_path = f"@{POSTS_STAGE}/{SOURCE_RUN_TAG}/raw_posts/{DEMO_RUN_ID}"
        print("      Uploading raw posts to stage...", end="", flush=True)
        cur.execute(
            f"PUT 'file://{post_file}' {post_stage_path} "
            f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        print("    ✅")
        print(f"      ✅ Snowpipe ({POSTS_STAGE.replace('STAGE', 'PIPE')}) "
              f"will auto-ingest raw posts into {POSTS_LANDING_TABLE}.")

        # --- PUT actors to stage (Snowpipe AUTO_INGEST handles the COPY) ---
        actor_file = (ACTOR_OUTPUT_DIR / ACTOR_FILENAME).resolve()
        actor_stage_path = f"@{ACTOR_STAGE}/{SOURCE_RUN_TAG}/actor_profiles/{DEMO_RUN_ID}"
        print("      Uploading actor profiles to stage...", end="", flush=True)
        cur.execute(
            f"PUT 'file://{actor_file}' {actor_stage_path} "
            f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        print(" ✅")
        print(f"      ✅ Snowpipe ({ACTOR_STAGE.replace('STAGE', 'PIPE')}) "
              f"will auto-ingest actor profiles into {ACTOR_LANDING_TABLE}.")

        # Manually nudge the pipes so we don't have to wait on AUTO_INGEST
        # event-notification latency for the demo.
        cur.execute("ALTER PIPE RAW.BLUESKY_RAW_POSTS_PIPE REFRESH")
        cur.execute("ALTER PIPE RAW.BLUESKY_ACTOR_PROFILES_PIPE REFRESH")

        return 0, 0

    except Exception as e:
        print(f"\n  ❌ Step failed: {e}")
        print("  Check your Snowflake credentials and schema setup.")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Step 5: Confirm
# ---------------------------------------------------------------------------


def _confirm_counts() -> None:
    """Query Snowflake and print confirmation table."""

    import time

    import snowflake.connector

    creds = _validate_env()

    print("\n[5/5] Confirming data in Snowflake...")
    print("      Waiting 60 seconds for Snowpipe to ingest...")
    time.sleep(60)

    try:
        conn = snowflake.connector.connect(
            account=creds["SNOWFLAKE_ACCOUNT"],
            user=creds["SNOWFLAKE_USER"],
            password=creds["SNOWFLAKE_PASSWORD"],
            role=creds["SNOWFLAKE_ROLE"],
            warehouse=creds["SNOWFLAKE_WAREHOUSE"],
            database=creds["SNOWFLAKE_DATABASE"],
            schema=creds["SNOWFLAKE_SCHEMA"],
            autocommit=True,
        )
        cur = conn.cursor()

        cur.execute(
            f"SELECT COUNT(*) FROM {POSTS_LANDING_TABLE} "
            f"WHERE source_run_tag = '{SOURCE_RUN_TAG}'"
        )
        post_count = cur.fetchone()[0]

        cur.execute(
            f"SELECT COUNT(*) FROM {ACTOR_LANDING_TABLE} "
            f"WHERE source_run_tag = '{SOURCE_RUN_TAG}'"
        )
        actor_count = cur.fetchone()[0]

        cur.close()
        conn.close()

    except Exception as e:
        print(f"\n  ❌ Step failed: {e}")
        print("  Could not verify row counts in Snowflake.")
        sys.exit(1)

    # Print confirmation table
    print()
    print("  ┌─────────────────────────────────┬────────────┐")
    print("  │ Table                           │ Row Count  │")
    print("  ├─────────────────────────────────┼────────────┤")
    print(f"  │ {POSTS_LANDING_TABLE:<31} │ {post_count:>10} │")
    print(f"  │ {ACTOR_LANDING_TABLE:<31} │ {actor_count:>10} │")
    print("  └─────────────────────────────────┴────────────┘")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 60)
    print("  BLUESKY PIPELINE — LIVE DEMO LOAD")
    print("=" * 60)

    # Step 1 + 2: Capture posts from firehose
    posts = _capture_posts()

    # Step 3: Fetch actor profiles
    actors = _fetch_actor_profiles(posts)

    # Step 4: Load to Snowflake
    _load_to_snowflake(len(posts), len(actors))

    # Step 5: Confirm
    _confirm_counts()

    print()
    print("=" * 60)
    print("  DEMO COMPLETE — Live Bluesky data is now in Snowflake")
    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ── Cleanup SQL (run in Snowflake to remove demo data) ───────────────────
#
# DELETE FROM RAW.LANDING_RAW_POSTS WHERE source_run_tag = 'demo_run';
# DELETE FROM RAW.LANDING_ACTOR_PROFILES WHERE source_run_tag = 'demo_run';
# REMOVE @RAW.BLUESKY_RAW_POSTS_STAGE/demo_raw_posts.jsonl.gz;
# REMOVE @RAW.BLUESKY_ACTOR_PROFILES_STAGE/demo_actor_profiles.jsonl.gz;
