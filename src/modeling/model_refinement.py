"""Deterministic local model refinement and ablation utilities for Phase 28."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .baseline_model import (
    BaggedDecisionStumpEnsemble,
    ModelingConfig,
    SoftmaxRegressionClassifier,
    build_column_groups,
    compute_classification_metrics,
    inspect_feature_schema,
    prepare_modeling_dataset,
)

TARGET_COLUMN = "engagement_label"
DEFAULT_BASELINE_METRICS_PATH = Path("local/derived/modeling/baseline_model_metrics.json")
DEFAULT_BASELINE_SUMMARY_PATH = Path("local/derived/modeling/baseline_model_summary.json")
DEFAULT_BASELINE_CONFUSION_PATH = Path("local/derived/modeling/baseline_confusion_matrix.csv")
DEFAULT_BASELINE_IMPORTANCE_PATH = Path("local/derived/modeling/baseline_feature_importance.parquet")

DEFAULT_REFINED_OUTPUT_DIR = Path("local/derived/modeling")
DEFAULT_REFINED_SAMPLE_CSV_PATH = Path("data/samples/refined_predictions_sample_1000.csv")

REQUIRED_BASELINE_KEYS = {
    "best_model_name",
    "models",
    "target_column",
    "model_feature_columns",
    "split",
}

TREND_FEATURE_HINTS = {
    "has_candidate",
    "has_trend_match",
    "match_stage",
    "match_score",
    "trend_counts",
    "trend_num_hours",
    "is_ambiguous",
    "is_ambiguous_match",
    "is_matched",
    "candidate_count",
    "matched_candidate_count",
    "matched_candidate_rate",
    "trend_date_available",
    "trend_post_day_diff",
    "same_day_trend_match",
}
POST_TEXT_FEATURE_HINTS = {
    "post_token_count",
    "post_char_count",
    "post_unique_token_count",
    "post_unique_token_ratio",
    "raw_exclamation_count",
    "raw_question_count",
    "raw_uppercase_ratio",
    "has_hashtag",
    "has_url",
    "has_mention",
    "has_special_chars",
    "has_non_ascii",
}
ACTOR_FEATURE_HINTS = {
    "actor_profile_found",
    "actor_followers_count",
    "actor_follows_count",
    "actor_posts_count",
    "actor_followers_to_follows_ratio",
    "actor_has_display_name",
    "actor_has_description",
    "actor_description_char_count",
    "actor_has_avatar",
    "actor_has_banner",
    "followers_count",
    "follows_count",
    "posts_count",
    "has_avatar",
    "has_banner",
    "display_name",
    "description",
}
TEMPORAL_FEATURE_HINTS = {
    "post_hour_utc",
    "post_day_of_week",
    "post_is_weekend",
    "post_month",
    "trend_post_day_diff",
    "same_day_trend_match",
}


@dataclass(frozen=True)
class RefinementConfig:
    """Configuration for deterministic refinement and ablation."""

    random_seed: int = 42
    test_size: float = 0.30
    sample_output_size: int = 1000
    logistic_learning_rate: float = 0.08
    logistic_max_iter: int = 1600
    logistic_l2: float = 0.002
    stump_estimators: int = 200
    stump_threshold_count: int = 9
    tuned_stump_estimators: int = 400
    tuned_stump_threshold_count: int = 13
    stump_max_features: int | None = None
    minority_class_label: str = "HIGH"
    material_recall_drop_tolerance: float = 0.05


@dataclass(frozen=True)
class RefinementExperiment:
    """Single refinement experiment specification."""

    name: str
    model_family: str
    params: dict[str, Any] = field(default_factory=dict)
    balanced_resample: bool = False
    removed_feature_groups: tuple[str, ...] = field(default_factory=tuple)


def read_baseline_artifacts(
    metrics_path: Path | str = DEFAULT_BASELINE_METRICS_PATH,
    summary_path: Path | str = DEFAULT_BASELINE_SUMMARY_PATH,
    confusion_path: Path | str = DEFAULT_BASELINE_CONFUSION_PATH,
    importance_path: Path | str = DEFAULT_BASELINE_IMPORTANCE_PATH,
) -> dict[str, Any]:
    """Load and validate baseline artifacts used for refinement decisions."""

    metrics_file = Path(metrics_path)
    if not metrics_file.exists():
        raise FileNotFoundError(f"Baseline metrics file not found: {metrics_file}")

    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_BASELINE_KEYS.difference(metrics.keys()))
    if missing:
        raise ValueError(f"Baseline metrics missing required keys: {missing}")
    if metrics.get("target_column") != TARGET_COLUMN:
        raise ValueError(
            f"Unexpected baseline target column: {metrics.get('target_column')} (expected {TARGET_COLUMN})"
        )

    summary_file = Path(summary_path)
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else None

    confusion_file = Path(confusion_path)
    confusion_df = pd.read_csv(confusion_file, index_col=0) if confusion_file.exists() else None

    importance_file = Path(importance_path)
    importance_df = pd.read_parquet(importance_file) if importance_file.exists() else None

    return {
        "metrics": metrics,
        "summary": summary,
        "confusion_matrix": confusion_df,
        "feature_importance": importance_df,
        "paths": {
            "metrics": str(metrics_file),
            "summary": str(summary_file) if summary_file.exists() else None,
            "confusion_matrix": str(confusion_file) if confusion_file.exists() else None,
            "feature_importance": str(importance_file) if importance_file.exists() else None,
        },
    }


def derive_feature_groups(model_feature_columns: list[str]) -> dict[str, list[str]]:
    """Derive deterministic feature groups from actual model feature columns."""

    cols = sorted(set(model_feature_columns))

    trend_match = sorted(
        [
            col
            for col in cols
            if col in TREND_FEATURE_HINTS or col.startswith("trend_") or col.startswith("match_")
        ]
    )
    post_text = sorted(
        [col for col in cols if col in POST_TEXT_FEATURE_HINTS or col.startswith("post_") or col.startswith("raw_")]
    )
    actor_account = sorted(
        [
            col
            for col in cols
            if col in ACTOR_FEATURE_HINTS or col.startswith("actor_") or col in {"followers_count", "follows_count", "posts_count"}
        ]
    )
    temporal = sorted([col for col in cols if col in TEMPORAL_FEATURE_HINTS or col.startswith("post_hour_")])

    return {
        "trend_match": trend_match,
        "post_text": post_text,
        "actor_account": actor_account,
        "temporal": temporal,
    }


def default_refinement_experiments(config: RefinementConfig | dict[str, Any] | None = None) -> list[RefinementExperiment]:
    """Return ordered, deterministic refinement experiment specs."""

    cfg = _resolve_config(config)
    return [
        RefinementExperiment(
            name="control_bagged_stump",
            model_family="bagged_stump",
            params={
                "n_estimators": cfg.stump_estimators,
                "threshold_count": cfg.stump_threshold_count,
                "max_features": cfg.stump_max_features,
            },
            balanced_resample=False,
        ),
        RefinementExperiment(
            name="bagged_stump_balanced_resample",
            model_family="bagged_stump",
            params={
                "n_estimators": cfg.stump_estimators,
                "threshold_count": cfg.stump_threshold_count,
                "max_features": cfg.stump_max_features,
            },
            balanced_resample=True,
        ),
        RefinementExperiment(
            name="bagged_stump_balanced_resample_tuned",
            model_family="bagged_stump",
            params={
                "n_estimators": cfg.tuned_stump_estimators,
                "threshold_count": cfg.tuned_stump_threshold_count,
                "max_features": cfg.stump_max_features,
            },
            balanced_resample=True,
        ),
        RefinementExperiment(
            name="softmax_refined_control",
            model_family="softmax",
            params={
                "learning_rate": cfg.logistic_learning_rate,
                "max_iter": cfg.logistic_max_iter,
                "l2": cfg.logistic_l2,
            },
            balanced_resample=False,
        ),
    ]


def class_balance_resample(
    X: np.ndarray,
    y: np.ndarray,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic class-balanced resampling of train data."""

    if X.shape[0] != y.shape[0]:
        raise ValueError("X and y row counts do not match for resampling")
    if y.size == 0:
        raise ValueError("Cannot resample empty target array")

    rng = np.random.RandomState(random_seed)
    unique_classes = np.unique(y)
    class_indices = {int(cls): np.where(y == cls)[0] for cls in unique_classes}
    max_count = max(len(idx) for idx in class_indices.values())

    selected: list[np.ndarray] = []
    for cls in sorted(class_indices.keys()):
        idx = class_indices[cls]
        if idx.size == 0:
            continue
        sampled = rng.choice(idx, size=max_count, replace=True)
        selected.append(sampled)

    balanced_idx = np.concatenate(selected) if selected else np.array([], dtype=int)
    if balanced_idx.size == 0:
        raise ValueError("Resampling produced no rows")
    rng.shuffle(balanced_idx)

    return X[balanced_idx], y[balanced_idx]


def run_refinement_experiments(
    feature_df: pd.DataFrame,
    baseline_metrics: dict[str, Any],
    config: RefinementConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the controlled Phase 28 refinement experiments."""

    cfg = _resolve_config(config)
    column_groups = build_column_groups(feature_df=feature_df, target_column=TARGET_COLUMN)
    baseline_model_columns = [
        col for col in baseline_metrics.get("model_feature_columns", []) if col in feature_df.columns
    ]
    if baseline_model_columns:
        column_groups = {
            **column_groups,
            "model_feature_columns": sorted(baseline_model_columns),
        }
    prepared = prepare_modeling_dataset(
        feature_df=feature_df,
        column_groups=column_groups,
        config=ModelingConfig(random_seed=cfg.random_seed, test_size=cfg.test_size),
    )
    feature_groups = derive_feature_groups(column_groups["model_feature_columns"])

    experiments = default_refinement_experiments(cfg)
    bundles: dict[str, dict[str, Any]] = {}
    summary_rows: list[dict[str, Any]] = []

    for experiment in experiments:
        bundle = _run_single_experiment(prepared=prepared, experiment=experiment, random_seed=cfg.random_seed)
        bundles[experiment.name] = bundle
        metrics = bundle["metrics"]
        summary_rows.append(
            {
                "experiment_name": experiment.name,
                "model_family": experiment.model_family,
                "balanced_resample": experiment.balanced_resample,
                "removed_feature_groups": list(experiment.removed_feature_groups),
                "n_features_used": int(prepared.X_train.shape[1]),
                "model_feature_column_count": int(len(column_groups["model_feature_columns"])),
                "accuracy": float(metrics["accuracy"]),
                "balanced_accuracy": float(metrics["balanced_accuracy"]),
                "macro_precision": float(metrics["macro_precision"]),
                "macro_recall": float(metrics["macro_recall"]),
                "macro_f1": float(metrics["macro_f1"]),
                "per_class": metrics["per_class"],
                "params": experiment.params,
            }
        )

    selected_name = _select_best_experiment_name(summary_rows)
    comparison = compare_baseline_vs_refined(
        baseline_metrics=baseline_metrics,
        refined_metrics=bundles[selected_name]["metrics"],
        minority_class_label=cfg.minority_class_label,
        material_recall_drop_tolerance=cfg.material_recall_drop_tolerance,
    )

    split_meta = {
        "train_size": int(prepared.y_train.shape[0]),
        "test_size": int(prepared.y_test.shape[0]),
        "test_size_ratio": float(prepared.y_test.shape[0] / (prepared.y_test.shape[0] + prepared.y_train.shape[0])),
        "class_labels": prepared.class_labels,
        "train_class_distribution": _class_distribution(prepared.y_train, prepared.class_labels),
        "test_class_distribution": _class_distribution(prepared.y_test, prepared.class_labels),
    }

    return {
        "column_groups": column_groups,
        "feature_groups": feature_groups,
        "split": split_meta,
        "experiments": summary_rows,
        "experiment_outputs": bundles,
        "selected_experiment_name": selected_name,
        "comparison_to_baseline": comparison,
    }


def run_ablation_experiments(
    feature_df: pd.DataFrame,
    selected_experiment: RefinementExperiment,
    feature_groups: dict[str, list[str]],
    model_feature_columns: list[str] | None = None,
    config: RefinementConfig | dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run required feature-group ablations using selected refined experiment setup."""

    cfg = _resolve_config(config)
    base_groups = build_column_groups(feature_df=feature_df, target_column=TARGET_COLUMN)
    if model_feature_columns:
        base_columns = sorted([col for col in model_feature_columns if col in feature_df.columns])
    else:
        base_columns = base_groups["model_feature_columns"]

    ablation_specs = [
        ("full_features", ()),
        ("no_trend_match_features", ("trend_match",)),
        ("no_post_text_features", ("post_text",)),
        ("no_actor_account_features", ("actor_account",)),
        ("no_temporal_features", ("temporal",)),
    ]

    rows: list[dict[str, Any]] = []
    for name, removed_groups in ablation_specs:
        removed_columns = sorted({col for group in removed_groups for col in feature_groups.get(group, [])})
        if removed_groups and not removed_columns:
            rows.append(
                {
                    "experiment_name": name,
                    "model_family": selected_experiment.model_family,
                    "removed_feature_groups": list(removed_groups),
                    "removed_feature_columns": [],
                    "n_features_used": int(len(base_columns)),
                    "skipped": True,
                    "skipped_reason": "feature_group_not_available",
                    "accuracy": np.nan,
                    "balanced_accuracy": np.nan,
                    "macro_precision": np.nan,
                    "macro_recall": np.nan,
                    "macro_f1": np.nan,
                    "per_class_json": None,
                }
            )
            continue

        model_cols = [col for col in base_columns if col not in removed_columns]
        if not model_cols:
            rows.append(
                {
                    "experiment_name": name,
                    "model_family": selected_experiment.model_family,
                    "removed_feature_groups": list(removed_groups),
                    "removed_feature_columns": removed_columns,
                    "n_features_used": 0,
                    "skipped": True,
                    "skipped_reason": "all_features_removed",
                    "accuracy": np.nan,
                    "balanced_accuracy": np.nan,
                    "macro_precision": np.nan,
                    "macro_recall": np.nan,
                    "macro_f1": np.nan,
                    "per_class_json": None,
                }
            )
            continue

        col_groups = {
            **base_groups,
            "model_feature_columns": model_cols,
        }
        prepared = prepare_modeling_dataset(
            feature_df=feature_df,
            column_groups=col_groups,
            config=ModelingConfig(random_seed=cfg.random_seed, test_size=cfg.test_size),
        )

        experiment = RefinementExperiment(
            name=name,
            model_family=selected_experiment.model_family,
            params=dict(selected_experiment.params),
            balanced_resample=selected_experiment.balanced_resample,
            removed_feature_groups=tuple(removed_groups),
        )
        bundle = _run_single_experiment(prepared=prepared, experiment=experiment, random_seed=cfg.random_seed)
        metrics = bundle["metrics"]

        rows.append(
            {
                "experiment_name": name,
                "model_family": selected_experiment.model_family,
                "removed_feature_groups": list(removed_groups),
                "removed_feature_columns": removed_columns,
                "n_features_used": int(prepared.X_train.shape[1]),
                "skipped": False,
                "skipped_reason": None,
                "accuracy": float(metrics["accuracy"]),
                "balanced_accuracy": float(metrics["balanced_accuracy"]),
                "macro_precision": float(metrics["macro_precision"]),
                "macro_recall": float(metrics["macro_recall"]),
                "macro_f1": float(metrics["macro_f1"]),
                "per_class_json": json.dumps(metrics["per_class"], sort_keys=True),
            }
        )

    ablation_df = pd.DataFrame(rows)
    ablation_df = ablation_df.sort_values("experiment_name", kind="stable").reset_index(drop=True)
    return ablation_df


def compare_baseline_vs_refined(
    baseline_metrics: dict[str, Any],
    refined_metrics: dict[str, Any],
    minority_class_label: str = "HIGH",
    material_recall_drop_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Compare baseline best metrics against refined selected metrics."""

    baseline_best_name = str(baseline_metrics["best_model_name"])
    baseline_best_metrics = baseline_metrics["models"][baseline_best_name]["metrics"]

    baseline_macro_f1 = float(baseline_best_metrics["macro_f1"])
    baseline_balanced = float(baseline_best_metrics["balanced_accuracy"])
    baseline_accuracy = float(baseline_best_metrics["accuracy"])

    refined_macro_f1 = float(refined_metrics["macro_f1"])
    refined_balanced = float(refined_metrics["balanced_accuracy"])
    refined_accuracy = float(refined_metrics["accuracy"])

    baseline_recall = float(baseline_best_metrics["per_class"].get(minority_class_label, {}).get("recall", 0.0))
    refined_recall = float(refined_metrics["per_class"].get(minority_class_label, {}).get("recall", 0.0))

    deltas = {
        "macro_f1_delta": refined_macro_f1 - baseline_macro_f1,
        "balanced_accuracy_delta": refined_balanced - baseline_balanced,
        "accuracy_delta": refined_accuracy - baseline_accuracy,
        f"{minority_class_label}_recall_delta": refined_recall - baseline_recall,
    }

    materially_worse_minority = refined_recall < (baseline_recall - material_recall_drop_tolerance)
    prefer_refined = (
        (refined_macro_f1 > baseline_macro_f1 + 1e-12)
        and (refined_balanced >= baseline_balanced - 1e-12)
        and not materially_worse_minority
    )

    return {
        "baseline_best_model_name": baseline_best_name,
        "baseline_best_metrics": baseline_best_metrics,
        "refined_selected_metrics": refined_metrics,
        "metric_deltas": {k: float(v) for k, v in deltas.items()},
        "minority_class_label": minority_class_label,
        "material_recall_drop_tolerance": float(material_recall_drop_tolerance),
        "materially_worse_minority_recall": bool(materially_worse_minority),
        "prefer_refined_model": bool(prefer_refined),
        "recommended_final_story": "refined" if prefer_refined else "baseline",
    }


def run_model_refinement(
    feature_df: pd.DataFrame,
    baseline_artifacts: dict[str, Any],
    config: RefinementConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run end-to-end Phase 28 refinement + ablation workflow."""

    cfg = _resolve_config(config)
    baseline_metrics = baseline_artifacts["metrics"]

    schema = inspect_feature_schema(feature_df)
    refinement = run_refinement_experiments(
        feature_df=feature_df,
        baseline_metrics=baseline_metrics,
        config=cfg,
    )

    selected_name = refinement["selected_experiment_name"]
    selected_output = refinement["experiment_outputs"][selected_name]
    selected_experiment = next(
        exp for exp in default_refinement_experiments(cfg) if exp.name == selected_name
    )

    ablation_df = run_ablation_experiments(
        feature_df=feature_df,
        selected_experiment=selected_experiment,
        feature_groups=refinement["feature_groups"],
        model_feature_columns=refinement["column_groups"]["model_feature_columns"],
        config=cfg,
    )

    return {
        "schema": schema,
        "config": asdict(cfg),
        "baseline_artifacts": {
            "paths": baseline_artifacts.get("paths", {}),
            "best_model_name": baseline_metrics.get("best_model_name"),
        },
        "column_groups": refinement["column_groups"],
        "feature_groups": refinement["feature_groups"],
        "split": refinement["split"],
        "refinement_experiments": refinement["experiments"],
        "selected_refined_experiment_name": selected_name,
        "comparison_to_baseline": refinement["comparison_to_baseline"],
        "model_ablation_results": ablation_df,
        "refined_feature_importance": selected_output["feature_importance"],
        "refined_prediction_sample": selected_output["prediction_sample"],
        "refined_confusion_matrix": selected_output["confusion_matrix"],
    }


def write_refinement_artifacts(
    modeling_output: dict[str, Any],
    output_dir: Path | str = DEFAULT_REFINED_OUTPUT_DIR,
    sample_csv_path: Path | str = DEFAULT_REFINED_SAMPLE_CSV_PATH,
) -> dict[str, str]:
    """Write required Phase 28 artifacts to disk."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_csv = Path(sample_csv_path)
    sample_csv.parent.mkdir(parents=True, exist_ok=True)

    metrics_path = out_dir / "refined_model_metrics.json"
    ablation_path = out_dir / "model_ablation_results.parquet"
    importance_path = out_dir / "refined_feature_importance.parquet"
    predictions_path = out_dir / "refined_predictions_sample.parquet"
    summary_path = out_dir / "model_refinement_summary.json"
    confusion_path = out_dir / "refined_confusion_matrix.csv"

    metrics_payload = {
        "config": modeling_output["config"],
        "target_column": modeling_output["column_groups"]["target_column"],
        "model_feature_columns": modeling_output["column_groups"]["model_feature_columns"],
        "feature_groups": modeling_output["feature_groups"],
        "split": modeling_output["split"],
        "baseline_artifacts": modeling_output["baseline_artifacts"],
        "refinement_experiments": modeling_output["refinement_experiments"],
        "selected_refined_experiment_name": modeling_output["selected_refined_experiment_name"],
        "comparison_to_baseline": modeling_output["comparison_to_baseline"],
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ablation_df: pd.DataFrame = modeling_output["model_ablation_results"]
    ablation_df.to_parquet(ablation_path, index=False)

    importance_df: pd.DataFrame = modeling_output["refined_feature_importance"]
    importance_df.to_parquet(importance_path, index=False)

    prediction_df: pd.DataFrame = modeling_output["refined_prediction_sample"]
    prediction_df.to_parquet(predictions_path, index=False)
    prediction_df.sort_values(["uri"] if "uri" in prediction_df.columns else prediction_df.columns[:1].tolist(), kind="stable").head(
        int(modeling_output["config"]["sample_output_size"])
    ).to_csv(sample_csv, index=False)

    confusion_df: pd.DataFrame = modeling_output["refined_confusion_matrix"]
    confusion_df.to_csv(confusion_path, index=True)

    summary_payload = {
        "schema": modeling_output["schema"],
        "config": modeling_output["config"],
        "column_groups": modeling_output["column_groups"],
        "feature_groups": modeling_output["feature_groups"],
        "split": modeling_output["split"],
        "selected_refined_experiment_name": modeling_output["selected_refined_experiment_name"],
        "comparison_to_baseline": modeling_output["comparison_to_baseline"],
        "ablation_overview": ablation_df.to_dict(orient="records"),
        "artifact_paths": {
            "metrics_json": str(metrics_path),
            "ablation_parquet": str(ablation_path),
            "feature_importance_parquet": str(importance_path),
            "prediction_sample_parquet": str(predictions_path),
            "prediction_sample_csv": str(sample_csv),
            "confusion_matrix_csv": str(confusion_path),
        },
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "metrics_json": str(metrics_path),
        "ablation_parquet": str(ablation_path),
        "feature_importance_parquet": str(importance_path),
        "prediction_sample_parquet": str(predictions_path),
        "prediction_sample_csv": str(sample_csv),
        "summary_json": str(summary_path),
        "confusion_matrix_csv": str(confusion_path),
    }


def _run_single_experiment(
    prepared: Any,
    experiment: RefinementExperiment,
    random_seed: int,
) -> dict[str, Any]:
    X_train = prepared.X_train
    y_train = prepared.y_train
    if experiment.balanced_resample:
        X_train, y_train = class_balance_resample(X_train, y_train, random_seed=random_seed)

    if experiment.model_family == "softmax":
        model = SoftmaxRegressionClassifier(
            learning_rate=float(experiment.params.get("learning_rate", 0.08)),
            max_iter=int(experiment.params.get("max_iter", 1600)),
            l2=float(experiment.params.get("l2", 0.002)),
            random_seed=random_seed,
        )
        class_counts = np.bincount(y_train, minlength=len(prepared.class_labels)).astype(float)
        class_weights = np.where(class_counts > 0, class_counts.sum() / (len(class_counts) * class_counts), 1.0)
        model.fit(X_train, y_train, class_weight=class_weights)
        probs = model.predict_proba(prepared.X_test)
        pred = np.argmax(probs, axis=1)
        importance_df = _build_softmax_importance(
            experiment_name=experiment.name,
            feature_names=prepared.feature_names,
            class_labels=prepared.class_labels,
            model=model,
        )
    elif experiment.model_family == "bagged_stump":
        model = BaggedDecisionStumpEnsemble(
            n_estimators=int(experiment.params.get("n_estimators", 200)),
            max_features=experiment.params.get("max_features"),
            threshold_count=int(experiment.params.get("threshold_count", 9)),
            random_seed=random_seed,
        )
        model.fit(X_train, y_train)
        probs = model.predict_proba(prepared.X_test)
        pred = np.argmax(probs, axis=1)
        importance_df = _build_stump_importance(
            experiment_name=experiment.name,
            feature_names=prepared.feature_names,
            model=model,
        )
    else:
        raise ValueError(f"Unsupported model family: {experiment.model_family}")

    metrics = compute_classification_metrics(prepared.y_test, pred, prepared.class_labels)
    confusion_df = pd.DataFrame(
        metrics["confusion_matrix"],
        index=prepared.class_labels,
        columns=prepared.class_labels,
    )
    prediction_df = _build_prediction_sample_single_model(
        prepared=prepared,
        experiment=experiment,
        probabilities=probs,
        predictions=pred,
    )

    return {
        "model": model,
        "metrics": metrics,
        "confusion_matrix": confusion_df,
        "prediction_sample": prediction_df,
        "feature_importance": importance_df,
    }


def _build_prediction_sample_single_model(
    prepared: Any,
    experiment: RefinementExperiment,
    probabilities: np.ndarray,
    predictions: np.ndarray,
) -> pd.DataFrame:
    debug = prepared.debug_test.copy()
    idx_to_label = {idx: label for idx, label in enumerate(prepared.class_labels)}

    debug["true_label"] = [idx_to_label[idx] for idx in prepared.y_test]
    debug["predicted_label"] = [idx_to_label[idx] for idx in predictions]
    debug["experiment_name"] = experiment.name
    debug["model_family"] = experiment.model_family
    debug["balanced_resample"] = experiment.balanced_resample
    debug["is_correct"] = debug["true_label"] == debug["predicted_label"]

    for idx, label in enumerate(prepared.class_labels):
        debug[f"prob_{label}"] = probabilities[:, idx]

    columns = [
        *(["uri"] if "uri" in debug.columns else []),
        *(["engagement_total"] if "engagement_total" in debug.columns else []),
        "true_label",
        "predicted_label",
        "experiment_name",
        "model_family",
        "balanced_resample",
        "is_correct",
    ]
    columns.extend([f"prob_{label}" for label in prepared.class_labels])
    passthrough = [
        col
        for col in [
            "match_stage",
            "match_score",
            "has_trend_match",
            "candidate_count",
            "matched_candidate_count",
            "post_token_count",
            "actor_followers_count",
        ]
        if col in debug.columns
    ]
    columns.extend(passthrough)
    columns = [col for col in columns if col in debug.columns]

    sort_cols = ["uri"] if "uri" in debug.columns else ["true_label"]
    return debug[columns].sort_values(sort_cols, kind="stable").reset_index(drop=True)


def _build_softmax_importance(
    experiment_name: str,
    feature_names: list[str],
    class_labels: list[str],
    model: SoftmaxRegressionClassifier,
) -> pd.DataFrame:
    if model.weights_ is None:
        raise ValueError("Softmax model missing fitted weights")

    rows: list[dict[str, Any]] = []
    mean_abs = np.mean(np.abs(model.weights_), axis=1)
    for idx, feature_name in enumerate(feature_names):
        rows.append(
            {
                "experiment_name": experiment_name,
                "model_name": "softmax_refined",
                "feature_name": feature_name,
                "importance": float(mean_abs[idx]),
                "class_label": "__all__",
                "signed_value": float(np.mean(model.weights_[idx, :])),
            }
        )
    for class_idx, class_label in enumerate(class_labels):
        for feat_idx, feature_name in enumerate(feature_names):
            coef = float(model.weights_[feat_idx, class_idx])
            rows.append(
                {
                    "experiment_name": experiment_name,
                    "model_name": "softmax_refined",
                    "feature_name": feature_name,
                    "importance": abs(coef),
                    "class_label": class_label,
                    "signed_value": coef,
                }
            )

    return pd.DataFrame(rows).sort_values(
        ["class_label", "importance", "feature_name"],
        ascending=[True, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _build_stump_importance(
    experiment_name: str,
    feature_names: list[str],
    model: BaggedDecisionStumpEnsemble,
) -> pd.DataFrame:
    if model.feature_importance_ is None:
        raise ValueError("Stump model missing fitted feature importance")

    rows = [
        {
            "experiment_name": experiment_name,
            "model_name": "bagged_stump_refined",
            "feature_name": feature_name,
            "importance": float(model.feature_importance_[idx]),
            "class_label": "__all__",
            "signed_value": float(model.feature_importance_[idx]),
        }
        for idx, feature_name in enumerate(feature_names)
    ]
    return pd.DataFrame(rows).sort_values(
        ["importance", "feature_name"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)


def _resolve_config(config: RefinementConfig | dict[str, Any] | None) -> RefinementConfig:
    if config is None:
        return RefinementConfig()
    if isinstance(config, RefinementConfig):
        return config
    return RefinementConfig(**config)


def _select_best_experiment_name(summary_rows: list[dict[str, Any]]) -> str:
    ranked = sorted(
        summary_rows,
        key=lambda row: (
            -float(row["macro_f1"]),
            -float(row["balanced_accuracy"]),
            -float(row["accuracy"]),
            row["experiment_name"],
        ),
    )
    return str(ranked[0]["experiment_name"])


def _class_distribution(y: np.ndarray, class_labels: list[str]) -> dict[str, int]:
    counts = np.bincount(y, minlength=len(class_labels))
    return {class_labels[idx]: int(count) for idx, count in enumerate(counts)}


__all__ = [
    "RefinementConfig",
    "RefinementExperiment",
    "class_balance_resample",
    "compare_baseline_vs_refined",
    "default_refinement_experiments",
    "derive_feature_groups",
    "read_baseline_artifacts",
    "run_ablation_experiments",
    "run_model_refinement",
    "run_refinement_experiments",
    "write_refinement_artifacts",
]
