from __future__ import annotations

import unittest

import pandas as pd

from src.nlp.topic_candidate_generation import (
    extract_topic_candidates_from_post,
    generate_topic_candidates_dataframe,
    normalize_candidate_phrase,
    summarize_topic_candidates,
)


class TopicCandidateGenerationTests(unittest.TestCase):
    def test_normalize_candidate_phrase_basic(self) -> None:
        normalized = normalize_candidate_phrase("  Small-Businesses!!!  ")
        self.assertEqual(normalized["candidate_phrase_clean"], "small businesses")
        self.assertEqual(normalized["candidate_phrase_alnum"], "small businesses")
        self.assertEqual(normalized["candidate_token_count"], 2)

    def test_null_and_blank_input_returns_no_candidates(self) -> None:
        result_null = extract_topic_candidates_from_post(
            uri="at://null",
            post_created_at="",
            post_text_raw=None,
            post_text_clean=None,
            post_text_alnum=None,
        )
        self.assertEqual(result_null, [])

        result_blank = extract_topic_candidates_from_post(
            uri="at://blank",
            post_created_at="",
            post_text_raw="",
            post_text_clean="",
            post_text_alnum="",
        )
        self.assertEqual(result_blank, [])

    def test_hashtag_extraction_and_no_hash_variant(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://hash",
            post_created_at="2026-04-04",
            post_text_raw="ISSO MILENA #bbb26",
            post_text_clean="isso milena #bbb26",
            post_text_alnum="isso milena bbb26",
        )
        hashtags = [c for c in candidates if c["candidate_source_type"] == "hashtag"]
        self.assertTrue(hashtags)
        self.assertEqual(hashtags[0]["candidate_phrase_clean"], "#bbb26")
        self.assertEqual(hashtags[0]["candidate_phrase_no_hash"], "bbb26")

    def test_preserves_useful_multiword_phrases(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://multi",
            post_created_at="2026-04-04",
            post_text_raw="small businesses need greater support",
            post_text_clean="small businesses need greater support",
            post_text_alnum="small businesses need greater support",
        )
        phrases = {c["candidate_phrase_alnum"] for c in candidates}
        self.assertIn("small businesses", phrases)
        self.assertIn("greater support", phrases)

    def test_filters_url_artifacts_but_keeps_useful_phrase(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://url",
            post_created_at="2026-04-04",
            post_text_raw="youtube.com/shorts/mmokh... GREAT STORY!!!",
            post_text_clean="youtube com shorts mmokh great story",
            post_text_alnum="youtube com shorts mmokh great story",
        )
        phrases = {c["candidate_phrase_alnum"] for c in candidates}
        self.assertNotIn("youtube com", phrases)
        self.assertNotIn("com shorts", phrases)
        self.assertIn("great story", phrases)

    def test_filters_id_like_macro_tokens(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://macro",
            post_created_at="2026-04-04",
            post_text_raw="macro: ku0kpgtkru7uxuj2lkcv",
            post_text_clean="macro ku0kpgtkru7uxuj2lkcv",
            post_text_alnum="macro ku0kpgtkru7uxuj2lkcv",
        )
        phrases = {c["candidate_phrase_alnum"] for c in candidates}
        self.assertNotIn("ku0kpgtkru7uxuj2lkcv", phrases)

    def test_filters_stopword_only_candidates(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://stop",
            post_created_at="2026-04-04",
            post_text_raw="the and of in",
            post_text_clean="the and of in",
            post_text_alnum="the and of in",
        )
        self.assertEqual(candidates, [])

    def test_collapses_duplicate_candidates_within_post(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://dup",
            post_created_at="2026-04-04",
            post_text_raw="small businesses small businesses",
            post_text_clean="small businesses small businesses",
            post_text_alnum="small businesses small businesses",
        )
        phrases = [c["candidate_phrase_alnum"] for c in candidates]
        self.assertEqual(phrases.count("small businesses"), 1)

    def test_deterministic_across_repeated_runs(self) -> None:
        kwargs = {
            "uri": "at://deterministic",
            "post_created_at": "2026-04-04",
            "post_text_raw": "small businesses need greater support #bbb26",
            "post_text_clean": "small businesses need greater support #bbb26",
            "post_text_alnum": "small businesses need greater support bbb26",
        }
        first = extract_topic_candidates_from_post(**kwargs)
        second = extract_topic_candidates_from_post(**kwargs)
        self.assertEqual(first, second)

    def test_emoji_only_near_empty_returns_no_candidates(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://emoji",
            post_created_at="2026-04-04",
            post_text_raw="🫂",
            post_text_clean="🫂",
            post_text_alnum="",
        )
        self.assertEqual(candidates, [])

    def test_mixed_language_non_ascii_phrase_is_preserved(self) -> None:
        candidates = extract_topic_candidates_from_post(
            uri="at://mixed",
            post_created_at="2026-04-04",
            post_text_raw="Que fofa, meu deus do céu",
            post_text_clean="que fofa meu deus do céu",
            post_text_alnum="que fofa meu deus do ceu",
        )
        phrases = {c["candidate_phrase_alnum"] for c in candidates}
        self.assertIn("meu deus", phrases)

    def test_dataframe_schema_validation_and_summary(self) -> None:
        bad_df = pd.DataFrame({"uri": ["at://1"]})
        with self.assertRaises(ValueError):
            generate_topic_candidates_dataframe(bad_df)

        prepared = pd.DataFrame(
            {
                "uri": ["at://1", "at://2"],
                "post_created_at": ["2026-04-04", "2026-04-04"],
                "post_text_raw": ["small businesses", ""],
                "post_text_clean": ["small businesses", ""],
                "post_text_alnum": ["small businesses", ""],
            }
        )
        generated = generate_topic_candidates_dataframe(prepared)
        summary = summarize_topic_candidates(prepared_posts_df=prepared, candidates_df=generated)
        self.assertEqual(summary["total_posts_processed"], 2)
        self.assertGreaterEqual(summary["posts_with_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
