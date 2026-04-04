from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.nlp.post_normalization import (
    discover_local_source_candidates,
    extract_post_text,
    normalize_post_text,
    prepare_bluesky_posts,
    select_best_local_source_candidate,
    summarize_prepared_posts,
)


class PostNormalizationTests(unittest.TestCase):
    def test_extract_post_text_prefers_record_text(self) -> None:
        row = {"record": {"text": "Hello Bluesky"}}
        self.assertEqual(extract_post_text(row), "Hello Bluesky")

    def test_extract_post_text_falls_back_to_empty(self) -> None:
        row = {"record": {"foo": "bar"}}
        self.assertEqual(extract_post_text(row), "")

    def test_extract_post_text_falls_back_to_top_level_text(self) -> None:
        row = {"text": "top-level text"}
        self.assertEqual(extract_post_text(row), "top-level text")

    def test_normalize_lowercase_and_whitespace(self) -> None:
        result = normalize_post_text("  HELLO   World  ")
        self.assertEqual(result["post_text_clean"], "hello world")
        self.assertEqual(result["post_token_count"], 2)
        self.assertEqual(result["post_char_count"], 11)

    def test_normalize_newline_and_tab_cleanup(self) -> None:
        result = normalize_post_text("Hello\tWorld\nAgain")
        self.assertEqual(result["post_text_clean"], "hello world again")

    def test_normalize_url_mention_hashtag_flags(self) -> None:
        result = normalize_post_text("Check https://x.com @alice #Trend")
        self.assertTrue(result["has_url"])
        self.assertTrue(result["has_mention"])
        self.assertTrue(result["has_hashtag"])

        result_bare_domain = normalize_post_text("watch this on youtube.com/shorts/abc")
        self.assertTrue(result_bare_domain["has_url"])

    def test_normalize_punctuation_and_alnum_helper(self) -> None:
        result = normalize_post_text("T-Mobile, wow!!!")
        self.assertEqual(result["post_text_clean"], "t mobile wow")
        self.assertEqual(result["post_text_alnum"], "t mobile wow")
        self.assertTrue(result["has_special_chars"])

    def test_normalize_non_ascii_and_curly_apostrophe(self) -> None:
        result = normalize_post_text("Flau’jae")
        self.assertEqual(result["post_text_clean"], "flau'jae")

        result_non_ascii = normalize_post_text("Beyoncé")
        self.assertEqual(result_non_ascii["post_text_clean"], "beyoncé")
        self.assertTrue(result_non_ascii["has_non_ascii"])

    def test_normalize_real_edge_case_bare_domain_text(self) -> None:
        result = normalize_post_text("youtube.com/shorts/mmokh... GREAT STORY!!!")
        self.assertEqual(result["post_text_clean"], "youtube com shorts mmokh great story")
        self.assertEqual(result["post_text_alnum"], "youtube com shorts mmokh great story")
        self.assertTrue(result["has_url"])

    def test_normalize_null_empty_handling(self) -> None:
        self.assertEqual(normalize_post_text(None)["post_text_clean"], "")
        self.assertEqual(normalize_post_text("")["post_token_count"], 0)

    def test_prepare_bluesky_posts_prefers_hydrated_row_for_text(self) -> None:
        raw_rows = [
            {
                "uri": "at://a",
                "record": {"text": "RAW text"},
                "record_created_at": "2026-01-01T00:00:00Z",
                "capture_run_id": "cap_1",
            }
        ]
        hydrated_rows = [
            {
                "uri": "at://a",
                "record": {"text": "HYDRATED text"},
                "hydrate_run_id": "hyd_1",
                "author_did": "did:plc:test",
                "indexed_at": "2026-01-01T00:00:01Z",
            }
        ]

        df = prepare_bluesky_posts(
            raw_rows=raw_rows,
            hydrated_rows=hydrated_rows,
            source_run_tag="phase6_diagnostic_20260401",
        )
        row = df.iloc[0]
        self.assertEqual(len(df), 1)
        self.assertEqual(row["uri"], "at://a")
        self.assertEqual(row["post_text_raw"], "HYDRATED text")
        self.assertEqual(row["text_source"], "hydrated_record_text")
        self.assertEqual(row["source_run_tag"], "phase6_diagnostic_20260401")

    def test_prepare_bluesky_posts_raw_fallback(self) -> None:
        raw_rows = [{"uri": "at://b", "record": {"text": "raw only"}}]
        hydrated_rows: list[dict[str, object]] = []
        df = prepare_bluesky_posts(
            raw_rows=raw_rows,
            hydrated_rows=hydrated_rows,
            source_run_tag="phase6_diagnostic_20260401",
        )
        row = df.iloc[0]
        self.assertEqual(row["post_text_raw"], "raw only")
        self.assertEqual(row["text_source"], "raw_record_text")

    def test_summarize_prepared_posts(self) -> None:
        raw_rows = [
            {"uri": "at://1", "record": {"text": "A A"}},
            {"uri": "at://2", "record": {"text": "A   A"}},
            {"uri": "at://3", "record": {"text": ""}},
        ]
        df = prepare_bluesky_posts(
            raw_rows=raw_rows,
            hydrated_rows=[],
            source_run_tag="sample",
        )
        summary = summarize_prepared_posts(df)
        self.assertEqual(summary["row_count"], 3)
        self.assertEqual(summary["non_empty_clean_text_count"], 2)
        self.assertEqual(summary["blank_clean_text_count"], 1)
        self.assertEqual(summary["duplicate_clean_text_rows_non_empty"], 1)

    def test_discover_and_select_best_local_source_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            run_a_raw = base / "run_a" / "raw_posts" / "cap_a"
            run_a_hyd = base / "run_a" / "hydrated_posts" / "hyd_a"
            run_b_raw = base / "run_b" / "raw_posts" / "cap_b"
            run_b_hyd = base / "run_b" / "hydrated_posts" / "hyd_b"
            run_a_raw.mkdir(parents=True, exist_ok=True)
            run_a_hyd.mkdir(parents=True, exist_ok=True)
            run_b_raw.mkdir(parents=True, exist_ok=True)
            run_b_hyd.mkdir(parents=True, exist_ok=True)

            self._write_jsonl_gz(
                run_a_raw / "raw_posts_000001.jsonl.gz",
                [{"uri": "at://a1", "record": {"text": ""}}],
            )
            self._write_jsonl_gz(
                run_a_hyd / "hydrated_posts_000001.jsonl.gz",
                [{"uri": "at://a1", "record": {"text": ""}}],
            )

            self._write_jsonl_gz(
                run_b_raw / "raw_posts_000001.jsonl.gz",
                [
                    {"uri": "at://b1", "record": {"text": "raw b1"}},
                    {"uri": "at://b2", "record": {"text": "raw b2"}},
                ],
            )
            self._write_jsonl_gz(
                run_b_hyd / "hydrated_posts_000001.jsonl.gz",
                [
                    {"uri": "at://b1", "record": {"text": "hydrated b1"}},
                    {"uri": "at://b2", "record": {"text": "hydrated b2"}},
                ],
            )

            candidates = discover_local_source_candidates(base)
            self.assertEqual(len(candidates), 2)

            selection = select_best_local_source_candidate(base)
            self.assertEqual(selection["selected"]["run_root_name"], "run_b")
            self.assertEqual(selection["selected"]["prepared_non_empty_text_count"], 2)

    @staticmethod
    def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row))
                handle.write("\n")


if __name__ == "__main__":
    unittest.main()
