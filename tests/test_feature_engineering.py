from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.features.feature_engineering import (
    FeatureConfig,
    build_local_engagement_feature_table,
    get_feature_column_groups,
    load_actor_profiles_file,
    load_hydrated_metrics_file,
    select_best_actor_profile_source_file,
    select_best_hydrated_source_file,
)


class FeatureEngineeringTests(unittest.TestCase):
    def test_schema_validation_fails_fast(self) -> None:
        prepared = pd.DataFrame([{"uri": "at://1"}])
        best = _best_matches_df([_best_row("at://1")])
        full = _full_matches_df([_full_row("at://1", 1, False)])
        hydrated = _hydrated_df([_hydrated_row("at://1", "did:plc:a", 0, 0, 0, 0)])
        actors = _actor_df([_actor_row("did:plc:a", 1, 1, 1)])

        with self.assertRaises(ValueError):
            build_local_engagement_feature_table(prepared, best, full, hydrated, actors)

    def test_hydrated_selector_prefers_overlap_then_row_count(self) -> None:
        prepared = _prepared_df([
            _prepared_row("at://a", "did:plc:a"),
            _prepared_row("at://b", "did:plc:b"),
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path_a = base / "run1" / "hydrated_posts" / "hyd_1" / "hydrated_posts_000001.jsonl.gz"
            path_b = base / "run2" / "hydrated_posts" / "hyd_2" / "hydrated_posts_000001.jsonl.gz"
            path_a.parent.mkdir(parents=True, exist_ok=True)
            path_b.parent.mkdir(parents=True, exist_ok=True)

            _write_jsonl_gz(path_a, [_hydrated_json("at://a"), _hydrated_json("at://x"), _hydrated_json("at://y")])
            _write_jsonl_gz(path_b, [_hydrated_json("at://a"), _hydrated_json("at://b")])

            selection = select_best_hydrated_source_file(prepared, base)
            self.assertEqual(selection["selected"]["file_path"], path_b.as_posix())
            self.assertEqual(selection["selected"]["uri_overlap_count"], 2)

    def test_actor_selector_prefers_did_overlap(self) -> None:
        prepared = _prepared_df([
            _prepared_row("at://a", "did:plc:a"),
            _prepared_row("at://b", "did:plc:b"),
        ])

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path_a = base / "run1" / "actor_profiles" / "act_1" / "actor_profiles_000001.jsonl.gz"
            path_b = base / "run2" / "actor_profiles" / "act_2" / "actor_profiles_000001.jsonl.gz"
            path_a.parent.mkdir(parents=True, exist_ok=True)
            path_b.parent.mkdir(parents=True, exist_ok=True)

            _write_jsonl_gz(path_a, [_actor_json("did:plc:a"), _actor_json("did:plc:x")])
            _write_jsonl_gz(path_b, [_actor_json("did:plc:a"), _actor_json("did:plc:b")])

            selection = select_best_actor_profile_source_file(prepared, base)
            self.assertEqual(selection["selected"]["file_path"], path_b.as_posix())
            self.assertEqual(selection["selected"]["did_overlap_count"], 2)

    def test_label_assignment_quantile_mode(self) -> None:
        prepared = _prepared_df([
            _prepared_row("at://1", "did:plc:a"),
            _prepared_row("at://2", "did:plc:b"),
            _prepared_row("at://3", "did:plc:c"),
        ])
        best = _best_matches_df([_best_row("at://1"), _best_row("at://2"), _best_row("at://3")])
        full = _full_matches_df([
            _full_row("at://1", 1, False),
            _full_row("at://2", 2, True),
            _full_row("at://3", 3, True),
        ])
        hydrated = _hydrated_df([
            _hydrated_row("at://1", "did:plc:a", 0, 0, 0, 0),
            _hydrated_row("at://2", "did:plc:b", 1, 0, 0, 0),
            _hydrated_row("at://3", "did:plc:c", 5, 0, 0, 0),
        ])
        actors = _actor_df([
            _actor_row("did:plc:a", 10, 2, 3),
            _actor_row("did:plc:b", 20, 4, 6),
            _actor_row("did:plc:c", 30, 5, 9),
        ])

        features, summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)
        labels = features.set_index("uri")["engagement_label"].astype(str).to_dict()

        self.assertEqual(summary["labeling"]["rule"], "quantile_bins")
        self.assertEqual(labels["at://1"], "LOW")
        self.assertEqual(labels["at://2"], "MEDIUM")
        self.assertEqual(labels["at://3"], "HIGH")

    def test_label_assignment_fallback_mode_when_quantiles_collapse(self) -> None:
        uris = [f"at://{idx}" for idx in range(6)]
        prepared = _prepared_df([_prepared_row(uri, f"did:plc:{idx}") for idx, uri in enumerate(uris)])
        best = _best_matches_df([_best_row(uri) for uri in uris])
        full = _full_matches_df([_full_row(uri, idx + 1, False) for idx, uri in enumerate(uris)])
        hydrated = _hydrated_df([
            _hydrated_row("at://0", "did:plc:0", 0, 0, 0, 0),
            _hydrated_row("at://1", "did:plc:1", 0, 0, 0, 0),
            _hydrated_row("at://2", "did:plc:2", 0, 0, 0, 0),
            _hydrated_row("at://3", "did:plc:3", 0, 0, 0, 0),
            _hydrated_row("at://4", "did:plc:4", 0, 0, 0, 0),
            _hydrated_row("at://5", "did:plc:5", 1, 0, 0, 0),
        ])
        actors = _actor_df([_actor_row(f"did:plc:{idx}", 10, 1, 1) for idx in range(6)])

        features, summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)

        self.assertEqual(summary["labeling"]["rule"], "fallback_count_bins")
        label_counts = features["engagement_label"].astype(str).value_counts().to_dict()
        self.assertEqual(label_counts.get("LOW"), 5)
        self.assertEqual(label_counts.get("MEDIUM"), 1)

    def test_label_assignment_fallback_when_quantile_bins_leave_empty_class(self) -> None:
        uris = [f"at://x{idx}" for idx in range(5)]
        prepared = _prepared_df([_prepared_row(uri, f"did:plc:x{idx}") for idx, uri in enumerate(uris)])
        best = _best_matches_df([_best_row(uri) for uri in uris])
        full = _full_matches_df([_full_row(uri, idx + 1, False) for idx, uri in enumerate(uris)])
        hydrated = _hydrated_df([
            _hydrated_row("at://x0", "did:plc:x0", 0, 0, 0, 0),
            _hydrated_row("at://x1", "did:plc:x1", 0, 0, 0, 0),
            _hydrated_row("at://x2", "did:plc:x2", 0, 0, 0, 0),
            _hydrated_row("at://x3", "did:plc:x3", 1, 0, 0, 0),
            _hydrated_row("at://x4", "did:plc:x4", 1, 0, 0, 0),
        ])
        actors = _actor_df([_actor_row(f"did:plc:x{idx}", 1, 1, 1) for idx in range(5)])

        features, summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)
        label_counts = features["engagement_label"].astype(str).value_counts().to_dict()

        self.assertEqual(summary["labeling"]["rule"], "fallback_count_bins")
        self.assertEqual(summary["labeling"]["fallback_reason"], "collapsed_quantile_or_empty_class")
        self.assertEqual(label_counts.get("LOW"), 3)
        self.assertEqual(label_counts.get("MEDIUM"), 2)

    def test_join_behavior_preserves_base_rows(self) -> None:
        prepared = _prepared_df([
            _prepared_row("at://1", "did:plc:a"),
            _prepared_row("at://2", "did:plc:b"),
            _prepared_row("at://3", "did:plc:c"),
        ])
        best = _best_matches_df([_best_row("at://1"), _best_row("at://2")])
        full = _full_matches_df([
            _full_row("at://1", 1, True),
            _full_row("at://2", 2, False),
        ])
        hydrated = _hydrated_df([
            _hydrated_row("at://1", "did:plc:a", 1, 0, 0, 0),
            _hydrated_row("at://2", "did:plc:b", 0, 0, 0, 0),
        ])
        actors = _actor_df([_actor_row("did:plc:a", 5, 1, 1)])

        features, summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)

        self.assertEqual(len(features), 3)
        self.assertEqual(summary["join_coverage"]["prepared_to_best_match"]["matched_rows"], 2)
        self.assertEqual(summary["join_coverage"]["with_hydrated_metrics"]["matched_rows"], 2)
        self.assertEqual(summary["join_coverage"]["with_actor_profiles"]["matched_rows"], 1)

    def test_feature_derivation_and_grouping(self) -> None:
        prepared = _prepared_df([
            _prepared_row(
                "at://1",
                "did:plc:a",
                post_text_raw="VOMO!!! WHY?",
                post_text_clean="vomo why",
                post_text_alnum="vomo why",
                post_token_count=2,
                post_char_count=8,
            )
        ])
        best = _best_matches_df([_best_row("at://1", match_stage="semantic", is_matched=True, match_score=0.7)])
        full = _full_matches_df([
            _full_row("at://1", 1, True),
            _full_row("at://1", 2, False),
        ])
        hydrated = _hydrated_df([_hydrated_row("at://1", "did:plc:a", 3, 1, 0, 0)])
        actors = _actor_df([_actor_row("did:plc:a", 100, 10, 30, display_name="Alice", description="Bio")])

        features, _ = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)
        row = features.iloc[0]

        self.assertEqual(int(row["candidate_count"]), 2)
        self.assertEqual(int(row["matched_candidate_count"]), 1)
        self.assertAlmostEqual(float(row["matched_candidate_rate"]), 0.5)
        self.assertEqual(int(row["raw_exclamation_count"]), 3)
        self.assertEqual(int(row["raw_question_count"]), 1)
        self.assertGreater(float(row["raw_uppercase_ratio"]), 0.8)
        self.assertTrue(bool(row["actor_profile_found"]))

        groups = get_feature_column_groups(features)
        self.assertNotIn("engagement_total", groups["model_feature_columns"])
        self.assertNotIn("engagement_label", groups["model_feature_columns"])
        self.assertIn("match_score", groups["model_feature_columns"])

    def test_loaders_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            hyd_path = base / "hydrated_posts_000001.jsonl.gz"
            act_path = base / "actor_profiles_000001.jsonl.gz"

            _write_jsonl_gz(
                hyd_path,
                [
                    {
                        **_hydrated_json("at://1"),
                        "author_did": "did:plc:a",
                        "author_handle": "a.bsky.social",
                        "like_count": 2,
                        "reply_count": 1,
                        "repost_count": 0,
                        "quote_count": 0,
                        "hydrated_at": "2026-04-01T00:00:01Z",
                        "indexed_at": "2026-04-01T00:00:00Z",
                    }
                ],
            )
            _write_jsonl_gz(
                act_path,
                [
                    {
                        **_actor_json("did:plc:a"),
                        "followers_count": 10,
                        "follows_count": 2,
                        "posts_count": 3,
                    }
                ],
            )

            hydrated = load_hydrated_metrics_file(hyd_path)
            actors = load_actor_profiles_file(act_path)

            prepared = _prepared_df([_prepared_row("at://1", "did:plc:a")])
            best = _best_matches_df([_best_row("at://1")])
            full = _full_matches_df([_full_row("at://1", 1, True)])

            first_df, first_summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)
            second_df, second_summary = build_local_engagement_feature_table(prepared, best, full, hydrated, actors)

            self.assertTrue(first_df.equals(second_df))
            self.assertEqual(first_summary, second_summary)


def _prepared_row(
    uri: str,
    did: str,
    *,
    post_text_raw: str = "Hello world",
    post_text_clean: str = "hello world",
    post_text_alnum: str = "hello world",
    post_token_count: int = 2,
    post_char_count: int = 11,
) -> dict[str, object]:
    return {
        "uri": uri,
        "post_created_at": "2026-04-01T18:49:39.359Z",
        "source_run_tag": "phase6_diagnostic_20260401",
        "text_source": "hydrated_record_text",
        "hydrated_author_did": did,
        "hydrated_author_handle": f"{did}.bsky.social",
        "post_text_raw": post_text_raw,
        "post_text_clean": post_text_clean,
        "post_text_alnum": post_text_alnum,
        "post_token_count": post_token_count,
        "post_char_count": post_char_count,
        "has_hashtag": False,
        "has_url": False,
        "has_mention": False,
        "has_special_chars": True,
        "has_non_ascii": False,
    }


def _best_row(
    uri: str,
    *,
    match_stage: str = "unmatched",
    match_score: float = 0.0,
    is_matched: bool = False,
) -> dict[str, object]:
    return {
        "uri": uri,
        "match_stage": match_stage,
        "match_score": match_score,
        "match_method": "none" if not is_matched else "difflib",
        "temporal_pool_mode": "global_fallback_no_date_overlap",
        "trend_name_clean": "",
        "trend_date": "",
        "trend_counts": 0.0,
        "trend_num_hours": 0.0,
        "is_matched": is_matched,
        "is_ambiguous": False,
    }


def _full_row(uri: str, candidate_id: int, is_matched: bool) -> dict[str, object]:
    return {
        "uri": uri,
        "candidate_id": candidate_id,
        "is_matched": is_matched,
    }


def _hydrated_row(
    uri: str,
    did: str,
    like_count: float,
    reply_count: float,
    repost_count: float,
    quote_count: float,
) -> dict[str, object]:
    return {
        "uri": uri,
        "author_did": did,
        "author_handle": f"{did}.bsky.social",
        "like_count": like_count,
        "reply_count": reply_count,
        "repost_count": repost_count,
        "quote_count": quote_count,
    }


def _actor_row(
    did: str,
    followers_count: float,
    follows_count: float,
    posts_count: float,
    *,
    display_name: str = "",
    description: str = "",
) -> dict[str, object]:
    return {
        "did": did,
        "handle": f"{did}.bsky.social",
        "followers_count": followers_count,
        "follows_count": follows_count,
        "posts_count": posts_count,
        "display_name": display_name,
        "description": description,
        "has_avatar": False,
        "has_banner": False,
    }


def _hydrated_json(uri: str) -> dict[str, object]:
    return {
        "uri": uri,
        "author_did": "did:plc:test",
        "author_handle": "test.bsky.social",
        "like_count": 0,
        "reply_count": 0,
        "repost_count": 0,
        "quote_count": 0,
        "indexed_at": "2026-04-01T00:00:00Z",
        "hydrated_at": "2026-04-01T00:00:00Z",
        "capture_run_id": "cap_1",
        "hydrate_run_id": "hyd_1",
    }


def _actor_json(did: str) -> dict[str, object]:
    return {
        "did": did,
        "handle": f"{did}.bsky.social",
        "followers_count": 1,
        "follows_count": 1,
        "posts_count": 1,
        "display_name": "name",
        "description": "desc",
        "profile": {},
        "created_at": "2026-03-01T00:00:00Z",
        "indexed_at": "2026-03-01T00:00:01Z",
        "actor_run_id": "act_1",
    }


def _prepared_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _best_matches_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _full_matches_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _hydrated_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _actor_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


if __name__ == "__main__":
    unittest.main()
