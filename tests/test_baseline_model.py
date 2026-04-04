from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.modeling.baseline_model import (
    ModelingConfig,
    build_column_groups,
    compute_classification_metrics,
    prepare_modeling_dataset,
    run_baseline_modeling,
    stratified_train_test_split_indices,
    write_modeling_artifacts,
)


class BaselineModelTests(unittest.TestCase):
    def test_build_column_groups_excludes_leakage_and_debug(self) -> None:
        df = _synthetic_feature_df()
        groups = build_column_groups(df)

        self.assertEqual(groups["target_column"], "engagement_label")
        self.assertIn("engagement_total", groups["excluded_columns"]["leakage"])
        self.assertIn("uri", groups["debug_columns"])
        self.assertNotIn("engagement_total", groups["model_feature_columns"])
        self.assertNotIn("uri", groups["model_feature_columns"])
        self.assertIn("candidate_count", groups["model_feature_columns"])

    def test_stratified_split_is_deterministic(self) -> None:
        y = np.array([0] * 8 + [1] * 6 + [2] * 4, dtype=int)

        train_a, test_a = stratified_train_test_split_indices(y, test_size=0.3, random_seed=7)
        train_b, test_b = stratified_train_test_split_indices(y, test_size=0.3, random_seed=7)

        self.assertTrue(np.array_equal(train_a, train_b))
        self.assertTrue(np.array_equal(test_a, test_b))

    def test_metric_computation_known_case(self) -> None:
        y_true = np.array([0, 1, 2, 0, 1, 2], dtype=int)
        y_pred = np.array([0, 1, 1, 0, 2, 2], dtype=int)
        labels = ["LOW", "MEDIUM", "HIGH"]

        metrics = compute_classification_metrics(y_true, y_pred, labels)

        self.assertAlmostEqual(metrics["accuracy"], 4 / 6)
        self.assertIn("macro_f1", metrics)
        self.assertEqual(len(metrics["confusion_matrix"]), 3)
        self.assertEqual(metrics["per_class"]["LOW"]["support"], 2)

    def test_prepare_and_run_pipeline_deterministic(self) -> None:
        df = _synthetic_feature_df()

        out_a = run_baseline_modeling(df, config=ModelingConfig(random_seed=11, logistic_max_iter=600, stump_estimators=100))
        out_b = run_baseline_modeling(df, config=ModelingConfig(random_seed=11, logistic_max_iter=600, stump_estimators=100))

        self.assertEqual(out_a["results"]["best_model_name"], out_b["results"]["best_model_name"])
        self.assertEqual(
            out_a["results"]["models"]["softmax_regression"]["metrics"],
            out_b["results"]["models"]["softmax_regression"]["metrics"],
        )
        self.assertTrue(
            out_a["results"]["prediction_sample"].equals(out_b["results"]["prediction_sample"])
        )

    def test_artifact_writer_outputs_expected_files_and_schema(self) -> None:
        df = _synthetic_feature_df()
        modeling_output = run_baseline_modeling(
            df,
            config=ModelingConfig(random_seed=3, logistic_max_iter=500, stump_estimators=60),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            outputs = write_modeling_artifacts(
                modeling_output=modeling_output,
                output_dir=base / "modeling",
                sample_csv_path=base / "samples" / "baseline_predictions_sample_1000.csv",
            )

            for key, path_str in outputs.items():
                self.assertTrue(Path(path_str).exists(), f"missing {key}: {path_str}")

            pred_df = pd.read_parquet(outputs["prediction_sample_parquet"])
            self.assertIn("true_label", pred_df.columns)
            self.assertIn("predicted_label", pred_df.columns)
            self.assertIn("best_model_name", pred_df.columns)

            imp_df = pd.read_parquet(outputs["feature_importance_parquet"])
            self.assertIn("model_name", imp_df.columns)
            self.assertIn("feature_name", imp_df.columns)
            self.assertIn("importance", imp_df.columns)

    def test_prepare_modeling_dataset_has_non_empty_train_test(self) -> None:
        df = _synthetic_feature_df()
        groups = build_column_groups(df)
        prepared = prepare_modeling_dataset(df, groups, ModelingConfig(random_seed=5))

        self.assertGreater(prepared.X_train.shape[0], 0)
        self.assertGreater(prepared.X_test.shape[0], 0)
        self.assertEqual(prepared.X_train.shape[1], prepared.X_test.shape[1])
        self.assertEqual(len(prepared.class_labels), 3)


def _synthetic_feature_df(n: int = 36) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for idx in range(n):
        if idx < 14:
            label = "LOW"
            engagement = 0.0
            match_score = 0.05
            followers = 100.0
        elif idx < 26:
            label = "MEDIUM"
            engagement = 1.0
            match_score = 0.45
            followers = 600.0
        else:
            label = "HIGH"
            engagement = 3.0
            match_score = 0.85
            followers = 2000.0

        rows.append(
            {
                "uri": f"at://post/{idx}",
                "post_created_at": "2026-04-01T18:49:39.359Z",
                "source_run_tag": "phase6_diagnostic_20260401",
                "text_source": "hydrated_record_text",
                "post_text_raw": f"post {idx}",
                "post_text_clean": f"post {idx}",
                "post_text_alnum": f"post {idx}",
                "engagement_label": label,
                "engagement_total": engagement,
                "eng_like_count": engagement,
                "eng_reply_count": 0.0,
                "eng_repost_count": 0.0,
                "eng_quote_count": 0.0,
                "like_count": engagement,
                "reply_count": 0.0,
                "repost_count": 0.0,
                "quote_count": 0.0,
                "match_stage": "unmatched" if label == "LOW" else "semantic",
                "match_score": match_score,
                "candidate_count": 0 if label == "LOW" else (5 if label == "MEDIUM" else 9),
                "matched_candidate_count": 0 if label == "LOW" else (1 if label == "MEDIUM" else 2),
                "matched_candidate_rate": 0.0 if label == "LOW" else (0.2 if label == "MEDIUM" else 0.22),
                "has_trend_match": label != "LOW",
                "trend_counts": 0.0 if label == "LOW" else (10000.0 if label == "MEDIUM" else 50000.0),
                "trend_num_hours": 0.0 if label == "LOW" else 2.0,
                "post_token_count": 5 if label == "LOW" else (12 if label == "MEDIUM" else 20),
                "post_char_count": 30 if label == "LOW" else (80 if label == "MEDIUM" else 140),
                "has_hashtag": False,
                "has_url": False,
                "has_mention": False,
                "has_special_chars": False,
                "has_non_ascii": False,
                "post_unique_token_count": 4 if label == "LOW" else (9 if label == "MEDIUM" else 14),
                "post_unique_token_ratio": 0.8 if label == "LOW" else (0.75 if label == "MEDIUM" else 0.7),
                "raw_exclamation_count": 0 if label == "LOW" else 1,
                "raw_question_count": 0,
                "raw_uppercase_ratio": 0.05 if label == "LOW" else (0.10 if label == "MEDIUM" else 0.15),
                "actor_followers_count": followers,
                "actor_follows_count": 50.0,
                "actor_posts_count": 1000.0,
                "actor_followers_to_follows_ratio": followers / 50.0,
                "actor_profile_found": True,
                "actor_has_display_name": True,
                "actor_has_description": True,
                "actor_description_char_count": 80.0,
                "actor_has_avatar": True,
                "actor_has_banner": True,
                "debug_high_cardinality": f"debug_{idx}",
            }
        )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
