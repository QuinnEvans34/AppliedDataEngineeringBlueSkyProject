from __future__ import annotations

import unittest

import pandas as pd

from src.nlp.trend_normalization import (
    normalize_trend_name,
    normalize_twitter_trending_dataframe,
    summarize_duplicate_impact,
)


class TrendNormalizationTests(unittest.TestCase):
    def test_lowercase_and_whitespace_normalization(self) -> None:
        result = normalize_trend_name("  ELITE   8  ")
        self.assertEqual(result["trend_name_clean"], "elite 8")
        self.assertEqual(result["trend_name_clean_no_hash"], "elite 8")
        self.assertEqual(result["trend_name_token_count"], 2)
        self.assertEqual(result["trend_name_char_count"], 7)

    def test_hashtag_preservation_and_no_hash_variant(self) -> None:
        result = normalize_trend_name(" #SmackDown ")
        self.assertTrue(result["is_hashtag"])
        self.assertEqual(result["trend_name_clean"], "#smackdown")
        self.assertEqual(result["trend_name_clean_no_hash"], "smackdown")
        self.assertEqual(result["normalized_key_with_hash"], "#smackdown")
        self.assertEqual(result["normalized_key_no_hash"], "smackdown")

    def test_punctuation_handling_and_curly_apostrophe(self) -> None:
        result = normalize_trend_name("Flau’jae, T-Mobile & Co.")
        self.assertEqual(result["trend_name_clean"], "flau jae t mobile co")
        self.assertEqual(result["trend_name_clean_no_hash"], "flau jae t mobile co")
        self.assertTrue(result["has_special_chars"])

    def test_separator_cleanup_including_slash_and_underscore(self) -> None:
        result = normalize_trend_name("A/B_C-D")
        self.assertEqual(result["trend_name_clean"], "a b c d")

    def test_ticker_variant_and_alnum_key(self) -> None:
        result = normalize_trend_name("$TSLA!!!")
        self.assertEqual(result["trend_name_clean"], "$tsla")
        self.assertEqual(result["trend_name_clean_no_hash"], "$tsla")
        self.assertEqual(result["trend_name_clean_no_dollar"], "tsla")
        self.assertEqual(result["trend_name_alnum"], "tsla")

    def test_url_like_handling_is_deterministic(self) -> None:
        result = normalize_trend_name("https://x.com/path")
        self.assertEqual(result["trend_name_clean"], "https x com path")
        self.assertTrue(result["has_url_like"])

    def test_non_ascii_and_blank_flags(self) -> None:
        result = normalize_trend_name("#عيد_الفطر_المبارك")
        self.assertTrue(result["is_hashtag"])
        self.assertTrue(result["has_non_ascii"])
        self.assertEqual(result["trend_name_clean"], "#عيد الفطر المبارك")

        blank = normalize_trend_name("   ")
        self.assertTrue(blank["is_blank_raw"])
        self.assertEqual(blank["trend_name_clean"], "")

    def test_null_and_empty_handling(self) -> None:
        null_result = normalize_trend_name(None)
        self.assertEqual(null_result["trend_name_raw"], "")
        self.assertEqual(null_result["trend_name_clean"], "")
        self.assertEqual(null_result["trend_name_token_count"], 0)
        self.assertEqual(null_result["trend_name_char_count"], 0)

        empty_result = normalize_trend_name("")
        self.assertEqual(empty_result["trend_name_clean_no_hash"], "")
        self.assertFalse(empty_result["is_hashtag"])

    def test_dataframe_normalization_preserves_source_columns(self) -> None:
        source = pd.DataFrame(
            {
                "num_hours": [2],
                "date": ["2026-03-31"],
                "name": ["#SmackDown"],
                "counts": [12345.0],
            }
        )
        normalized = normalize_twitter_trending_dataframe(source)

        for col in ["num_hours", "date", "name", "counts"]:
            self.assertIn(col, normalized.columns)

        self.assertEqual(normalized.loc[0, "trend_name_raw"], "#SmackDown")
        self.assertEqual(normalized.loc[0, "trend_name_clean"], "#smackdown")
        self.assertEqual(normalized.loc[0, "trend_name_clean_no_hash"], "smackdown")
        self.assertEqual(normalized.loc[0, "trend_name_alnum"], "smackdown")
        self.assertEqual(normalized.loc[0, "normalized_date"], "2026-03-31")

    def test_duplicate_impact_summary_detects_collapses(self) -> None:
        source = pd.DataFrame(
            {
                "date": ["2024-04-01", "2024-04-01", "2024-04-01", "2024-04-02"],
                "name": ["#SmackDown", "#Smackdown", "SmackDown", "Good Friday"],
                "num_hours": [1, 1, 2, 3],
                "counts": [10.0, 20.0, 30.0, 40.0],
            }
        )
        normalized = normalize_twitter_trending_dataframe(source)
        summary = summarize_duplicate_impact(source, normalized)
        self.assertGreaterEqual(
            summary["duplicate_date_normalized_no_hash_after"],
            summary["duplicate_date_name_before"],
        )
        self.assertGreaterEqual(
            summary["collapsed_key_count_with_multi_raw_variants"], 1
        )


if __name__ == "__main__":
    unittest.main()
