from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.modeling.model_refinement import (
    RefinementConfig,
    RefinementExperiment,
    class_balance_resample,
    compare_baseline_vs_refined,
    default_refinement_experiments,
    derive_feature_groups,
    run_ablation_experiments,
    run_model_refinement,
    write_refinement_artifacts,
)


class ModelRefinementTests(unittest.TestCase):
    def test_derive_feature_groups_real_like_columns(self) -> None:
        model_cols = [
            "match_stage",
            "match_score",
            "trend_counts",
            "candidate_count",
            "post_token_count",
            "post_char_count",
            "raw_question_count",
            "actor_followers_count",
            "actor_followers_to_follows_ratio",
            "post_hour_utc",
            "post_day_of_week",
        ]
        groups = derive_feature_groups(model_cols)

        self.assertIn("match_stage", groups["trend_match"])
        self.assertIn("post_token_count", groups["post_text"])
        self.assertIn("actor_followers_count", groups["actor_account"])
        self.assertIn("post_hour_utc", groups["temporal"])

    def test_default_experiment_order_is_deterministic(self) -> None:
        a = default_refinement_experiments(RefinementConfig(random_seed=7))
        b = default_refinement_experiments(RefinementConfig(random_seed=7))

        self.assertEqual([exp.name for exp in a], [exp.name for exp in b])
        self.assertEqual([exp.model_family for exp in a], [exp.model_family for exp in b])

    def test_class_balance_resample_reproducible(self) -> None:
        X = np.arange(30, dtype=float).reshape(10, 3)
        y = np.array([0] * 6 + [1] * 3 + [2], dtype=int)

        X_a, y_a = class_balance_resample(X, y, random_seed=11)
        X_b, y_b = class_balance_resample(X, y, random_seed=11)

        self.assertTrue(np.array_equal(X_a, X_b))
        self.assertTrue(np.array_equal(y_a, y_b))
        counts = np.bincount(y_a)
        self.assertEqual(int(counts[0]), int(counts[1]))
        self.assertEqual(int(counts[1]), int(counts[2]))

    def test_ablation_skip_when_feature_group_missing(self) -> None:
        df = _synthetic_feature_df(include_temporal=False)
        selected = RefinementExperiment(
            name="bagged_stump_balanced_resample",
            model_family="bagged_stump",
            params={"n_estimators": 80, "threshold_count": 7, "max_features": None},
            balanced_resample=True,
        )
        groups = derive_feature_groups(
            [
                "match_stage",
                "match_score",
                "candidate_count",
                "post_token_count",
                "post_char_count",
                "actor_followers_count",
            ]
        )
        ablation = run_ablation_experiments(
            feature_df=df,
            selected_experiment=selected,
            feature_groups=groups,
            config=RefinementConfig(random_seed=5, test_size=0.25),
        )
        row = ablation.loc[ablation["experiment_name"] == "no_temporal_features"].iloc[0]

        self.assertTrue(bool(row["skipped"]))
        self.assertEqual(str(row["skipped_reason"]), "feature_group_not_available")

    def test_compare_baseline_vs_refined_logic(self) -> None:
        baseline = {
            "best_model_name": "bagged_stump_ensemble",
            "models": {
                "bagged_stump_ensemble": {
                    "metrics": {
                        "accuracy": 0.75,
                        "balanced_accuracy": 0.50,
                        "macro_precision": 0.57,
                        "macro_recall": 0.50,
                        "macro_f1": 0.50,
                        "per_class": {
                            "HIGH": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 1},
                            "LOW": {"precision": 0.7, "recall": 1.0, "f1": 0.82, "support": 4},
                            "MEDIUM": {"precision": 1.0, "recall": 0.5, "f1": 0.67, "support": 2},
                        },
                    }
                }
            },
        }
        refined = {
            "accuracy": 0.78,
            "balanced_accuracy": 0.56,
            "macro_precision": 0.61,
            "macro_recall": 0.56,
            "macro_f1": 0.55,
            "per_class": {
                "HIGH": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 1},
                "LOW": {"precision": 0.8, "recall": 0.8, "f1": 0.8, "support": 4},
                "MEDIUM": {"precision": 0.6, "recall": 0.4, "f1": 0.48, "support": 2},
            },
        }
        comparison = compare_baseline_vs_refined(baseline, refined)

        self.assertTrue(comparison["prefer_refined_model"])
        self.assertEqual(comparison["recommended_final_story"], "refined")

    def test_end_to_end_pipeline_and_artifacts(self) -> None:
        df = _synthetic_feature_df(include_temporal=True)
        baseline_metrics = _baseline_metrics_fixture()

        output = run_model_refinement(
            feature_df=df,
            baseline_artifacts={"metrics": baseline_metrics, "paths": {}},
            config=RefinementConfig(random_seed=13, test_size=0.25, stump_estimators=80, tuned_stump_estimators=120),
        )

        self.assertIn("refinement_experiments", output)
        self.assertIn("model_ablation_results", output)
        self.assertIn("refined_feature_importance", output)
        self.assertIn("refined_prediction_sample", output)
        self.assertIn("comparison_to_baseline", output)

        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            artifacts = write_refinement_artifacts(
                modeling_output=output,
                output_dir=base / "modeling",
                sample_csv_path=base / "samples" / "refined_predictions_sample_1000.csv",
            )

            for path in artifacts.values():
                self.assertTrue(Path(path).exists())

            pred_df = pd.read_parquet(artifacts["prediction_sample_parquet"])
            self.assertIn("true_label", pred_df.columns)
            self.assertIn("predicted_label", pred_df.columns)
            self.assertIn("experiment_name", pred_df.columns)

            abl_df = pd.read_parquet(artifacts["ablation_parquet"])
            self.assertIn("experiment_name", abl_df.columns)
            self.assertIn("macro_f1", abl_df.columns)

    def test_repeated_runs_are_deterministic(self) -> None:
        df = _synthetic_feature_df(include_temporal=True)
        baseline_metrics = _baseline_metrics_fixture()
        cfg = RefinementConfig(random_seed=21, test_size=0.25, stump_estimators=90, tuned_stump_estimators=120)

        out_a = run_model_refinement(df, {"metrics": baseline_metrics, "paths": {}}, config=cfg)
        out_b = run_model_refinement(df, {"metrics": baseline_metrics, "paths": {}}, config=cfg)

        self.assertEqual(out_a["selected_refined_experiment_name"], out_b["selected_refined_experiment_name"])
        self.assertEqual(out_a["refinement_experiments"], out_b["refinement_experiments"])
        self.assertTrue(out_a["model_ablation_results"].equals(out_b["model_ablation_results"]))


def _baseline_metrics_fixture() -> dict[str, object]:
    return {
        "best_model_name": "bagged_stump_ensemble",
        "target_column": "engagement_label",
        "split": {"train_size": 24, "test_size": 12},
        "model_feature_columns": [
            "match_stage",
            "match_score",
            "candidate_count",
            "post_token_count",
            "actor_followers_count",
            "post_hour_utc",
        ],
        "models": {
            "bagged_stump_ensemble": {
                "metrics": {
                    "accuracy": 0.62,
                    "balanced_accuracy": 0.46,
                    "macro_precision": 0.50,
                    "macro_recall": 0.46,
                    "macro_f1": 0.44,
                    "per_class": {
                        "HIGH": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 3},
                        "LOW": {"precision": 0.7, "recall": 0.8, "f1": 0.75, "support": 5},
                        "MEDIUM": {"precision": 0.5, "recall": 0.6, "f1": 0.55, "support": 4},
                    },
                }
            }
        },
    }


def _synthetic_feature_df(n: int = 45, include_temporal: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(n):
        if idx < 21:
            label = "LOW"
            engagement = 0.0
            followers = 80.0 + idx
            match_score = 0.05
            candidate_count = 0
        elif idx < 34:
            label = "MEDIUM"
            engagement = 1.0
            followers = 400.0 + idx * 2
            match_score = 0.45
            candidate_count = 4
        else:
            label = "HIGH"
            engagement = 3.0
            followers = 1200.0 + idx * 3
            match_score = 0.85
            candidate_count = 8

        row = {
            "uri": f"at://post/{idx}",
            "post_created_at": "2026-04-01T18:49:39.359Z",
            "source_run_tag": "phase6_diagnostic_20260401",
            "text_source": "hydrated_record_text",
            "post_text_raw": f"Post number {idx}",
            "post_text_clean": f"post number {idx}",
            "post_text_alnum": f"post number {idx}",
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
            "candidate_count": candidate_count,
            "matched_candidate_count": 0 if label == "LOW" else 1,
            "matched_candidate_rate": 0.0 if label == "LOW" else 0.2,
            "has_candidate": label != "LOW",
            "has_trend_match": label != "LOW",
            "is_ambiguous": False,
            "is_ambiguous_match": False,
            "is_matched": label != "LOW",
            "trend_counts": 0.0 if label == "LOW" else (12000.0 if label == "MEDIUM" else 80000.0),
            "trend_num_hours": 0.0 if label == "LOW" else 2.0,
            "trend_date_available": label != "LOW",
            "trend_post_day_diff": 0.0 if label != "LOW" else 1.0,
            "post_token_count": 5 if label == "LOW" else (11 if label == "MEDIUM" else 18),
            "post_char_count": 25 if label == "LOW" else (70 if label == "MEDIUM" else 140),
            "post_unique_token_count": 4 if label == "LOW" else (8 if label == "MEDIUM" else 14),
            "post_unique_token_ratio": 0.80 if label == "LOW" else (0.73 if label == "MEDIUM" else 0.68),
            "raw_question_count": 0 if label == "LOW" else 1,
            "raw_exclamation_count": 0 if label == "LOW" else 1,
            "raw_uppercase_ratio": 0.04 if label == "LOW" else (0.08 if label == "MEDIUM" else 0.12),
            "has_hashtag": idx % 6 == 0,
            "has_url": idx % 10 == 0,
            "has_mention": False,
            "has_special_chars": True,
            "has_non_ascii": idx % 8 == 0,
            "actor_profile_found": True,
            "actor_followers_count": followers,
            "actor_follows_count": 50.0,
            "actor_posts_count": 1000.0,
            "actor_followers_to_follows_ratio": followers / 50.0,
            "actor_has_display_name": True,
            "actor_has_description": True,
            "actor_description_char_count": 90.0,
            "actor_has_avatar": True,
            "actor_has_banner": True,
            "followers_count": followers,
            "follows_count": 50.0,
            "posts_count": 1000.0,
            "has_banner": True,
        }
        if include_temporal:
            row["post_hour_utc"] = float((idx % 24))
            row["post_day_of_week"] = float((idx % 7))
            row["post_is_weekend"] = bool((idx % 7) in (5, 6))
            row["post_month"] = 4.0

        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()

