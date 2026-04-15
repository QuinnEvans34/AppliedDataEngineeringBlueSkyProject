"""
Bluesky Pipeline — Unified Demo Orchestrator

Single entrypoint that runs the full demo flow in the correct order:
  1. capture posts from firehose + fetch actor profiles (demo_load)
  2. PUT both files to RAW stages, refresh pipes
  3. wait for Snowpipe ingest, confirm raw counts
  4. run NLP trend matching against the captured posts
  5. PUT trend-match results, refresh pipe
  6. trend-match landing now triggers ENHANCED.TASK_ENRICH_POSTS,
     which chains into ENHANCED.TASK_BUILD_ML_READY

Run from repo root:
    python scripts/demo/run_full_demo_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_load import (  # noqa: E402
    _capture_posts,
    _fetch_actor_profiles,
    _load_to_snowflake as _load_posts_and_actors,
    _confirm_counts,
)
from run_trend_matching import (  # noqa: E402
    _load_demo_posts,
    _load_trends,
    _run_nlp_pipeline,
    _load_to_snowflake as _load_trend_matches,
)


def _banner(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> int:
    _banner("BLUESKY PIPELINE — UNIFIED DEMO RUN")

    _banner("STAGE 1/2 — RAW POSTS + ACTOR PROFILES")
    posts = _capture_posts()
    actors = _fetch_actor_profiles(posts)
    _load_posts_and_actors(len(posts), len(actors))
    _confirm_counts()

    _banner("STAGE 2/2 — NLP TREND MATCHING")
    demo_posts = _load_demo_posts()
    trends_df = _load_trends()
    _, _, summary = _run_nlp_pipeline(demo_posts, trends_df)
    _load_trend_matches(summary)

    _banner("DEMO COMPLETE")
    print(
        "Trend-match landing has triggered ENHANCED.TASK_ENRICH_POSTS;\n"
        "ENHANCED.TASK_BUILD_ML_READY chains after it.\n"
        "Allow ~1–2 minutes, then run validation queries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
