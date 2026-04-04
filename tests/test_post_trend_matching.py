from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.nlp.post_trend_matching import (
    MatchConfig,
    match_post_candidates_to_trends,
    select_best_post_matches,
)


class PostTrendMatchingTests(unittest.TestCase):
    def test_exact_match_success(self) -> None:
        candidates = _candidates_df([
            _candidate(uri="at://1", phrase_clean="small business", phrase_alnum="small business"),
        ])
        trends = _trends_df([
            _trend(name="Small Business", key_no_hash="small business", date="2024-01-10", counts=100),
        ])

        full, best, summary = match_post_candidates_to_trends(candidates, trends)

        self.assertEqual(len(full), 1)
        self.assertEqual(full.loc[0, "match_stage"], "exact")
        self.assertEqual(full.loc[0, "match_score"], 1.0)
        self.assertTrue(full.loc[0, "is_matched"])
        self.assertEqual(best.loc[0, "match_stage"], "exact")
        self.assertEqual(summary["candidate_stage_counts"].get("exact"), 1)

    def test_fuzzy_match_above_threshold(self) -> None:
        candidates = _candidates_df([
            _candidate(uri="at://1", phrase_clean="small busines", phrase_alnum="small busines"),
        ])
        trends = _trends_df([
            _trend(name="Small Business", key_no_hash="small business", date="2024-01-10", counts=200),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.88, semantic_min_score=0.99)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(full.loc[0, "match_stage"], "fuzzy")
        self.assertGreaterEqual(full.loc[0, "match_score"], 0.88)

    def test_fuzzy_below_threshold_unmatched_when_semantic_high(self) -> None:
        candidates = _candidates_df([
            _candidate(uri="at://1", phrase_clean="zzzz", phrase_alnum="zzzz"),
        ])
        trends = _trends_df([
            _trend(name="Small Business", key_no_hash="small business", date="2024-01-10", counts=200),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.90, semantic_min_score=0.99)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(full.loc[0, "match_stage"], "unmatched")
        self.assertFalse(full.loc[0, "is_matched"])

    def test_semantic_fallback_only_after_exact_and_fuzzy_fail(self) -> None:
        candidates = _candidates_df([
            _candidate(
                uri="at://1",
                phrase_clean="economic relief support",
                phrase_alnum="economic relief support",
            ),
        ])
        trends = _trends_df([
            _trend(
                name="Relief Support Economic",
                key_no_hash="relief support economic",
                date="2024-01-10",
                counts=120,
            ),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.95, semantic_min_score=0.50)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(full.loc[0, "match_stage"], "semantic")
        self.assertGreaterEqual(full.loc[0, "semantic_token_cosine"], 0.90)

    def test_stage_priority_exact_wins_over_other_stages(self) -> None:
        candidates = _candidates_df(
            [
                _candidate(uri="at://post", rank=1, phrase_clean="alpha", phrase_alnum="alpha"),
                _candidate(uri="at://post", rank=2, phrase_clean="alpah", phrase_alnum="alpah"),
            ]
        )
        trends = _trends_df([
            _trend(name="Alpha", key_no_hash="alpha", date="2024-01-10", counts=50),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.80, semantic_min_score=0.40)
        full, best, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        exact_rows = full.loc[full["candidate_phrase_alnum"] == "alpha"]
        self.assertTrue((exact_rows["match_stage"] == "exact").all())
        self.assertEqual(best.loc[0, "match_stage"], "exact")

    def test_temporal_narrowing_window_hit(self) -> None:
        candidates = _candidates_df([
            _candidate(
                uri="at://1",
                post_created_at="2024-01-10T12:00:00Z",
                phrase_clean="alpha",
                phrase_alnum="alpha",
            ),
        ])
        trends = _trends_df(
            [
                _trend(name="Alpha Near", key_no_hash="alpha", date="2024-01-10", counts=5),
                _trend(name="Alpha Far", key_no_hash="alpha", date="2024-03-10", counts=999),
            ]
        )

        cfg = MatchConfig(date_window_days=0)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(len(full), 1)
        self.assertEqual(full.loc[0, "trend_name_raw"], "Alpha Near")
        self.assertEqual(full.loc[0, "temporal_pool_mode"], "date_window")

    def test_temporal_window_empty_falls_back_to_global(self) -> None:
        candidates = _candidates_df([
            _candidate(
                uri="at://1",
                post_created_at="2026-04-01T12:00:00Z",
                phrase_clean="alpha",
                phrase_alnum="alpha",
            ),
        ])
        trends = _trends_df([
            _trend(name="Alpha", key_no_hash="alpha", date="2024-01-10", counts=5),
        ])

        cfg = MatchConfig(date_window_days=0)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(full.loc[0, "match_stage"], "exact")
        self.assertEqual(full.loc[0, "temporal_pool_mode"], "global_fallback_no_date_overlap")

    def test_ambiguity_flag_when_multiple_exact_matches(self) -> None:
        candidates = _candidates_df([
            _candidate(uri="at://1", phrase_clean="alpha", phrase_alnum="alpha"),
        ])
        trends = _trends_df(
            [
                _trend(name="Alpha A", key_no_hash="alpha", date="2024-01-10", counts=5),
                _trend(name="Alpha B", key_no_hash="alpha", date="2024-01-10", counts=6),
            ]
        )

        cfg = MatchConfig(date_window_days=0)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertEqual(len(full), 2)
        self.assertTrue((full["is_ambiguous"] == True).all())
        self.assertTrue((full["ambiguity_count"] == 2).all())

    def test_best_match_selection_stage_score_counts_tiebreak(self) -> None:
        full = pd.DataFrame(
            [
                {
                    "candidate_id": 1,
                    "uri": "at://post",
                    "post_created_at": "2024-01-10T00:00:00Z",
                    "post_text_raw": "",
                    "post_text_clean": "",
                    "candidate_phrase_raw": "",
                    "candidate_phrase_clean": "",
                    "candidate_phrase_alnum": "x",
                    "candidate_source_type": "ngram_2",
                    "candidate_rank_in_post": 1,
                    "trend_id": 1,
                    "trend_date": "2024-01-10",
                    "trend_name_raw": "Trend Fuzzy",
                    "trend_name_clean": "trend fuzzy",
                    "trend_key_no_hash": "trend fuzzy",
                    "trend_counts": 100,
                    "trend_num_hours": 1,
                    "match_stage": "fuzzy",
                    "match_method": "difflib",
                    "match_score": 0.95,
                    "lexical_score": 0.95,
                    "semantic_token_cosine": np.nan,
                    "semantic_char_trigram_jaccard": np.nan,
                    "stage_rank": 1,
                    "temporal_pool_mode": "date_window",
                    "is_matched": True,
                    "is_ambiguous": False,
                    "ambiguity_count": 0,
                },
                {
                    "candidate_id": 2,
                    "uri": "at://post",
                    "post_created_at": "2024-01-10T00:00:00Z",
                    "post_text_raw": "",
                    "post_text_clean": "",
                    "candidate_phrase_raw": "",
                    "candidate_phrase_clean": "",
                    "candidate_phrase_alnum": "y",
                    "candidate_source_type": "ngram_2",
                    "candidate_rank_in_post": 2,
                    "trend_id": 2,
                    "trend_date": "2024-01-10",
                    "trend_name_raw": "Trend Exact",
                    "trend_name_clean": "trend exact",
                    "trend_key_no_hash": "trend exact",
                    "trend_counts": 10,
                    "trend_num_hours": 1,
                    "match_stage": "exact",
                    "match_method": "normalized_equality",
                    "match_score": 1.0,
                    "lexical_score": 1.0,
                    "semantic_token_cosine": np.nan,
                    "semantic_char_trigram_jaccard": np.nan,
                    "stage_rank": 1,
                    "temporal_pool_mode": "date_window",
                    "is_matched": True,
                    "is_ambiguous": False,
                    "ambiguity_count": 0,
                },
            ]
        )

        best = select_best_post_matches(full)
        self.assertEqual(len(best), 1)
        self.assertEqual(best.loc[0, "match_stage"], "exact")
        self.assertEqual(best.loc[0, "trend_name_raw"], "Trend Exact")

    def test_hashtag_and_noisy_and_empty_edge_cases(self) -> None:
        candidates = _candidates_df(
            [
                _candidate(uri="at://hash", phrase_clean="#bbb26", phrase_alnum="bbb26"),
                _candidate(uri="at://noise", phrase_clean="shorts mmokh", phrase_alnum="shorts mmokh"),
                _candidate(uri="at://empty", phrase_clean="", phrase_alnum=""),
            ]
        )
        trends = _trends_df([
            _trend(name="#bbb26", key_no_hash="bbb26", date="2024-01-10", counts=1),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.95, semantic_min_score=0.95)
        full, _, _ = match_post_candidates_to_trends(candidates, trends, cfg)

        row_hash = full.loc[full["uri"] == "at://hash"].iloc[0]
        row_noise = full.loc[full["uri"] == "at://noise"].iloc[0]
        row_empty = full.loc[full["uri"] == "at://empty"].iloc[0]

        self.assertEqual(row_hash["match_stage"], "exact")
        self.assertEqual(row_noise["match_stage"], "unmatched")
        self.assertEqual(row_empty["match_stage"], "unmatched")

    def test_deterministic_repeated_runs(self) -> None:
        candidates = _candidates_df([
            _candidate(uri="at://1", phrase_clean="small busines", phrase_alnum="small busines"),
            _candidate(uri="at://2", phrase_clean="", phrase_alnum=""),
        ])
        trends = _trends_df([
            _trend(name="Small Business", key_no_hash="small business", date="2024-01-10", counts=200),
            _trend(name="Completely Different", key_no_hash="completely different", date="2024-01-10", counts=10),
        ])

        cfg = MatchConfig(date_window_days=0, fuzzy_min_score=0.88, semantic_min_score=0.70)
        full_a, best_a, summary_a = match_post_candidates_to_trends(candidates, trends, cfg)
        full_b, best_b, summary_b = match_post_candidates_to_trends(candidates, trends, cfg)

        self.assertTrue(full_a.equals(full_b))
        self.assertTrue(best_a.equals(best_b))
        self.assertEqual(summary_a, summary_b)


def _candidate(
    *,
    uri: str,
    phrase_clean: str,
    phrase_alnum: str,
    post_created_at: str = "2024-01-10T00:00:00Z",
    source_type: str = "ngram_2",
    rank: int = 1,
) -> dict[str, object]:
    return {
        "uri": uri,
        "post_created_at": post_created_at,
        "post_text_raw": phrase_clean,
        "post_text_clean": phrase_clean,
        "post_text_alnum": phrase_alnum,
        "candidate_phrase_raw": phrase_clean,
        "candidate_phrase_clean": phrase_clean,
        "candidate_phrase_alnum": phrase_alnum,
        "candidate_source_type": source_type,
        "candidate_rank_in_post": rank,
    }


def _trend(
    *,
    name: str,
    key_no_hash: str,
    date: str,
    counts: float,
    num_hours: float = 1.0,
) -> dict[str, object]:
    return {
        "name": name,
        "normalized_key_no_hash": key_no_hash,
        "trend_name_clean": key_no_hash,
        "normalized_date": date,
        "counts": counts,
        "num_hours": num_hours,
    }


def _candidates_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _trends_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
