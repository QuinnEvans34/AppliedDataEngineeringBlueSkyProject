"""Deterministic local baseline modeling utilities for Phase 27."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TARGET_COLUMN = "engagement_label"
LEAKAGE_COLUMNS = {
    "engagement_label",
    "engagement_total",
    "eng_like_count",
    "eng_reply_count",
    "eng_repost_count",
    "eng_quote_count",
    "like_count",
    "reply_count",
    "repost_count",
    "quote_count",
}
DEFAULT_DEBUG_COLUMNS = {
    "uri",
    "post_created_at",
    "source_run_tag",
    "text_source",
    "hydrated_author_did",
    "hydrated_author_handle",
    "trend_name_clean",
    "trend_date",
    "match_method",
    "temporal_pool_mode",
    "eng_author_did",
    "eng_author_handle",
    "actor_did",
    "actor_handle",
    "post_text_raw",
    "post_text_clean",
    "post_text_alnum",
    "raw_source_row_json",
    "hydrated_source_row_json",
}


@dataclass(frozen=True)
class ModelingConfig:
    """Configuration for deterministic baseline modeling."""

    random_seed: int = 42
    test_size: float = 0.30
    logistic_learning_rate: float = 0.10
    logistic_max_iter: int = 1200
    logistic_l2: float = 0.001
    stump_estimators: int = 200
    stump_max_features: int | None = None
    stump_threshold_count: int = 9


@dataclass
class PreparedDataset:
    """Prepared train/test matrices and retained metadata."""

    X_train: np.ndarray
    X_test: np.ndarray
    y_train: np.ndarray
    y_test: np.ndarray
    train_index: np.ndarray
    test_index: np.ndarray
    class_labels: list[str]
    feature_names: list[str]
    model_feature_columns: list[str]
    label_columns: list[str]
    debug_columns: list[str]
    excluded_columns: dict[str, list[str]]
    debug_train: pd.DataFrame
    debug_test: pd.DataFrame


class SoftmaxRegressionClassifier:
    """Simple multinomial softmax regression optimized with gradient descent."""

    def __init__(
        self,
        learning_rate: float = 0.10,
        max_iter: int = 1200,
        l2: float = 0.001,
        random_seed: int = 42,
    ) -> None:
        self.learning_rate = learning_rate
        self.max_iter = max_iter
        self.l2 = l2
        self.random_seed = random_seed
        self.weights_: np.ndarray | None = None
        self.bias_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, class_weight: np.ndarray | None = None) -> "SoftmaxRegressionClassifier":
        n_samples, n_features = X.shape
        n_classes = int(np.max(y)) + 1

        rng = np.random.RandomState(self.random_seed)
        self.weights_ = rng.normal(loc=0.0, scale=0.01, size=(n_features, n_classes))
        self.bias_ = np.zeros(n_classes, dtype=float)

        y_one_hot = np.eye(n_classes)[y]

        sample_weights = np.ones(n_samples, dtype=float)
        if class_weight is not None:
            sample_weights = class_weight[y]
        sample_weights = sample_weights / np.mean(sample_weights)

        for _ in range(self.max_iter):
            logits = X @ self.weights_ + self.bias_
            probs = _softmax(logits)

            error = (probs - y_one_hot) * sample_weights[:, None]
            grad_w = (X.T @ error) / n_samples + self.l2 * self.weights_
            grad_b = np.sum(error, axis=0) / n_samples

            self.weights_ -= self.learning_rate * grad_w
            self.bias_ -= self.learning_rate * grad_b

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.weights_ is None or self.bias_ is None:
            raise ValueError("SoftmaxRegressionClassifier is not fitted")
        logits = X @ self.weights_ + self.bias_
        return _softmax(logits)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(X), axis=1)


class BaggedDecisionStumpEnsemble:
    """Random-forest-style bagged decision stumps for multiclass classification."""

    def __init__(
        self,
        n_estimators: int = 200,
        max_features: int | None = None,
        threshold_count: int = 9,
        random_seed: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_features = max_features
        self.threshold_count = threshold_count
        self.random_seed = random_seed
        self.stumps_: list[dict[str, Any]] = []
        self.n_classes_: int = 0
        self.feature_importance_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaggedDecisionStumpEnsemble":
        n_samples, n_features = X.shape
        self.n_classes_ = int(np.max(y)) + 1

        if n_samples == 0:
            raise ValueError("Cannot fit stump ensemble on empty data")

        rng = np.random.RandomState(self.random_seed)
        self.feature_importance_ = np.zeros(n_features, dtype=float)
        self.stumps_ = []

        max_features = self.max_features
        if max_features is None:
            max_features = max(1, int(np.sqrt(n_features)))
        max_features = max(1, min(int(max_features), n_features))

        for _ in range(self.n_estimators):
            sample_idx = rng.choice(n_samples, size=n_samples, replace=True)
            feature_idx = rng.choice(n_features, size=max_features, replace=False)

            X_sample = X[sample_idx]
            y_sample = y[sample_idx]

            stump = _fit_best_stump(
                X_sample=X_sample,
                y_sample=y_sample,
                feature_idx=feature_idx,
                n_classes=self.n_classes_,
                threshold_count=self.threshold_count,
            )
            self.stumps_.append(stump)

            if stump["feature"] >= 0:
                self.feature_importance_[stump["feature"]] += float(stump["gain"])

        total_gain = float(np.sum(self.feature_importance_))
        if total_gain > 0:
            self.feature_importance_ = self.feature_importance_ / total_gain

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.stumps_:
            raise ValueError("BaggedDecisionStumpEnsemble is not fitted")

        n_samples = X.shape[0]
        probs = np.zeros((n_samples, self.n_classes_), dtype=float)

        for stump in self.stumps_:
            if stump["feature"] < 0:
                probs += stump["default_probs"]
                continue

            col = stump["feature"]
            threshold = stump["threshold"]
            left_mask = X[:, col] <= threshold
            right_mask = ~left_mask

            probs[left_mask] += stump["left_probs"]
            probs[right_mask] += stump["right_probs"]

        probs = probs / len(self.stumps_)
        probs = probs / np.clip(probs.sum(axis=1, keepdims=True), 1e-12, None)
        return probs

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(X), axis=1)


def inspect_feature_schema(feature_df: pd.DataFrame) -> dict[str, Any]:
    """Return compact schema profile for feature dataset."""

    return {
        "row_count": int(len(feature_df)),
        "column_count": int(len(feature_df.columns)),
        "columns": feature_df.columns.tolist(),
        "dtype_counts": {
            str(dtype): int(count)
            for dtype, count in feature_df.dtypes.astype(str).value_counts().items()
        },
    }


def build_column_groups(
    feature_df: pd.DataFrame,
    feature_summary: dict[str, Any] | None = None,
    target_column: str = TARGET_COLUMN,
    max_categorical_cardinality: int = 12,
) -> dict[str, Any]:
    """Build explicit target/model/debug groups and exclusion audit."""

    if target_column not in feature_df.columns:
        raise ValueError(f"Target column not found: {target_column}")

    summary_debug = set()
    if feature_summary:
        summary_debug = set(feature_summary.get("feature_groups", {}).get("debug_columns", []))

    debug_columns = sorted({
        column
        for column in feature_df.columns
        if column in DEFAULT_DEBUG_COLUMNS or column in summary_debug
    })

    excluded_for_leakage = sorted([column for column in feature_df.columns if column in LEAKAGE_COLUMNS])
    excluded_debug = sorted([column for column in debug_columns if column in feature_df.columns and column != target_column])

    candidate_columns = [
        column
        for column in feature_df.columns
        if column not in LEAKAGE_COLUMNS
        and column != target_column
        and column not in debug_columns
    ]

    excluded_high_cardinality: list[str] = []
    excluded_unsupported_dtype: list[str] = []
    retained_model_columns: list[str] = []

    for column in candidate_columns:
        series = feature_df[column]
        non_null = series.dropna()

        if pd.api.types.is_bool_dtype(series):
            retained_model_columns.append(column)
            continue
        if pd.api.types.is_numeric_dtype(series):
            retained_model_columns.append(column)
            continue

        if isinstance(series.dtype, pd.CategoricalDtype) or pd.api.types.is_object_dtype(series):
            cardinality = int(non_null.astype(str).nunique())
            if cardinality <= max_categorical_cardinality:
                retained_model_columns.append(column)
            else:
                excluded_high_cardinality.append(column)
            continue

        excluded_unsupported_dtype.append(column)

    excluded_constant: list[str] = []
    final_model_columns: list[str] = []
    for column in retained_model_columns:
        cardinality = int(feature_df[column].astype(str).nunique(dropna=False))
        if cardinality <= 1:
            excluded_constant.append(column)
        else:
            final_model_columns.append(column)

    label_columns = [
        target_column,
        *[column for column in ["engagement_total", "eng_like_count", "eng_reply_count", "eng_repost_count", "eng_quote_count"] if column in feature_df.columns],
    ]

    return {
        "target_column": target_column,
        "model_feature_columns": sorted(final_model_columns),
        "label_columns": label_columns,
        "debug_columns": sorted([column for column in debug_columns if column in feature_df.columns]),
        "excluded_columns": {
            "leakage": excluded_for_leakage,
            "debug_reference": excluded_debug,
            "high_cardinality": sorted(excluded_high_cardinality),
            "unsupported_dtype": sorted(excluded_unsupported_dtype),
            "constant": sorted(excluded_constant),
        },
    }


def prepare_modeling_dataset(
    feature_df: pd.DataFrame,
    column_groups: dict[str, Any],
    config: ModelingConfig,
) -> PreparedDataset:
    """Prepare deterministic train/test matrices and metadata."""

    target_column = column_groups["target_column"]
    model_cols = column_groups["model_feature_columns"]
    debug_cols = column_groups["debug_columns"]
    label_cols = column_groups["label_columns"]

    if not model_cols:
        raise ValueError("No model feature columns selected")

    valid_df = feature_df.copy()
    valid_df[target_column] = valid_df[target_column].astype(str)
    valid_df = valid_df.loc[valid_df[target_column].str.len() > 0].reset_index(drop=True)

    class_labels = sorted(valid_df[target_column].unique().tolist())
    label_to_idx = {label: idx for idx, label in enumerate(class_labels)}
    y_all = valid_df[target_column].map(label_to_idx).to_numpy(dtype=int)

    train_idx, test_idx = stratified_train_test_split_indices(
        y=y_all,
        test_size=config.test_size,
        random_seed=config.random_seed,
    )

    train_df = valid_df.iloc[train_idx].reset_index(drop=True)
    test_df = valid_df.iloc[test_idx].reset_index(drop=True)

    encoder = _fit_feature_encoder(train_df[model_cols])
    X_train = _transform_with_encoder(train_df[model_cols], encoder)
    X_test = _transform_with_encoder(test_df[model_cols], encoder)

    y_train = train_df[target_column].map(label_to_idx).to_numpy(dtype=int)
    y_test = test_df[target_column].map(label_to_idx).to_numpy(dtype=int)

    return PreparedDataset(
        X_train=X_train,
        X_test=X_test,
        y_train=y_train,
        y_test=y_test,
        train_index=train_idx,
        test_index=test_idx,
        class_labels=class_labels,
        feature_names=encoder["feature_names"],
        model_feature_columns=model_cols,
        label_columns=label_cols,
        debug_columns=debug_cols,
        excluded_columns=column_groups["excluded_columns"],
        debug_train=train_df[[col for col in debug_cols + label_cols if col in train_df.columns]].copy(),
        debug_test=test_df[[col for col in debug_cols + label_cols if col in test_df.columns]].copy(),
    )


def stratified_train_test_split_indices(
    y: np.ndarray,
    test_size: float,
    random_seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic stratified split over class labels."""

    if y.size < 3:
        raise ValueError("Need at least 3 rows for stratified split")

    rng = np.random.RandomState(random_seed)

    train_parts: list[np.ndarray] = []
    test_parts: list[np.ndarray] = []

    for cls in sorted(np.unique(y)):
        cls_idx = np.where(y == cls)[0]
        cls_idx = cls_idx.copy()
        rng.shuffle(cls_idx)

        n_cls = len(cls_idx)
        if n_cls == 1:
            n_test = 0
        else:
            n_test = int(round(n_cls * test_size))
            n_test = max(1, min(n_test, n_cls - 1))

        test_parts.append(cls_idx[:n_test])
        train_parts.append(cls_idx[n_test:])

    train_idx = np.concatenate(train_parts) if train_parts else np.array([], dtype=int)
    test_idx = np.concatenate(test_parts) if test_parts else np.array([], dtype=int)

    train_idx = np.sort(train_idx)
    test_idx = np.sort(test_idx)

    if train_idx.size == 0 or test_idx.size == 0:
        raise ValueError("Stratified split produced empty train or test set")

    return train_idx, test_idx


def train_and_evaluate_baselines(
    prepared: PreparedDataset,
    config: ModelingConfig,
) -> dict[str, Any]:
    """Train linear and tree baselines and return metrics/artifacts."""

    class_counts = np.bincount(prepared.y_train, minlength=len(prepared.class_labels)).astype(float)
    class_weights = np.where(class_counts > 0, class_counts.sum() / (len(class_counts) * class_counts), 1.0)

    linear_model = SoftmaxRegressionClassifier(
        learning_rate=config.logistic_learning_rate,
        max_iter=config.logistic_max_iter,
        l2=config.logistic_l2,
        random_seed=config.random_seed,
    )
    linear_model.fit(prepared.X_train, prepared.y_train, class_weight=class_weights)
    linear_probs = linear_model.predict_proba(prepared.X_test)
    linear_pred = np.argmax(linear_probs, axis=1)

    tree_model = BaggedDecisionStumpEnsemble(
        n_estimators=config.stump_estimators,
        max_features=config.stump_max_features,
        threshold_count=config.stump_threshold_count,
        random_seed=config.random_seed,
    )
    tree_model.fit(prepared.X_train, prepared.y_train)
    tree_probs = tree_model.predict_proba(prepared.X_test)
    tree_pred = np.argmax(tree_probs, axis=1)

    metrics_linear = compute_classification_metrics(prepared.y_test, linear_pred, prepared.class_labels)
    metrics_tree = compute_classification_metrics(prepared.y_test, tree_pred, prepared.class_labels)

    models = {
        "softmax_regression": {
            "metrics": metrics_linear,
            "predictions": linear_pred,
            "probabilities": linear_probs,
            "model": linear_model,
        },
        "bagged_stump_ensemble": {
            "metrics": metrics_tree,
            "predictions": tree_pred,
            "probabilities": tree_probs,
            "model": tree_model,
        },
    }

    best_model_name = select_best_model_name(models)
    best_bundle = models[best_model_name]

    feature_importance_df = build_feature_importance_table(
        feature_names=prepared.feature_names,
        class_labels=prepared.class_labels,
        softmax_model=linear_model,
        stump_model=tree_model,
    )

    prediction_sample_df = build_prediction_sample(
        prepared=prepared,
        models=models,
        best_model_name=best_model_name,
    )

    confusion_df = pd.DataFrame(
        best_bundle["metrics"]["confusion_matrix"],
        index=prepared.class_labels,
        columns=prepared.class_labels,
    )

    return {
        "models": {
            name: {
                "metrics": bundle["metrics"],
            }
            for name, bundle in models.items()
        },
        "best_model_name": best_model_name,
        "best_model_criterion": "macro_f1_then_balanced_accuracy_then_accuracy",
        "feature_importance": feature_importance_df,
        "prediction_sample": prediction_sample_df,
        "confusion_matrix": confusion_df,
        "model_feature_columns": prepared.model_feature_columns,
        "label_columns": prepared.label_columns,
        "debug_columns": prepared.debug_columns,
        "excluded_columns": prepared.excluded_columns,
        "class_labels": prepared.class_labels,
        "split": {
            "train_size": int(len(prepared.y_train)),
            "test_size": int(len(prepared.y_test)),
            "test_size_ratio": float(len(prepared.y_test) / (len(prepared.y_test) + len(prepared.y_train))),
            "train_class_distribution": _class_distribution(prepared.y_train, prepared.class_labels),
            "test_class_distribution": _class_distribution(prepared.y_test, prepared.class_labels),
        },
    }


def select_best_model_name(models: dict[str, dict[str, Any]]) -> str:
    """Select best model by macro-F1, then balanced accuracy, then accuracy."""

    ranked = sorted(
        models.items(),
        key=lambda item: (
            -float(item[1]["metrics"]["macro_f1"]),
            -float(item[1]["metrics"]["balanced_accuracy"]),
            -float(item[1]["metrics"]["accuracy"]),
            item[0],
        ),
    )
    return ranked[0][0]


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_labels: list[str],
) -> dict[str, Any]:
    """Compute multi-class metrics without external ML libraries."""

    n_classes = len(class_labels)
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for true, pred in zip(y_true, y_pred, strict=False):
        cm[int(true), int(pred)] += 1

    total = int(np.sum(cm))
    accuracy = float(np.trace(cm) / total) if total else 0.0

    per_class: dict[str, dict[str, float]] = {}
    recalls = []
    precisions = []
    f1s = []
    for idx, label in enumerate(class_labels):
        tp = float(cm[idx, idx])
        fp = float(np.sum(cm[:, idx]) - tp)
        fn = float(np.sum(cm[idx, :]) - tp)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        per_class[label] = {
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "support": int(np.sum(cm[idx, :])),
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    return {
        "accuracy": float(accuracy),
        "balanced_accuracy": float(np.mean(recalls)) if recalls else 0.0,
        "macro_precision": float(np.mean(precisions)) if precisions else 0.0,
        "macro_recall": float(np.mean(recalls)) if recalls else 0.0,
        "macro_f1": float(np.mean(f1s)) if f1s else 0.0,
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
    }


def build_feature_importance_table(
    feature_names: list[str],
    class_labels: list[str],
    softmax_model: SoftmaxRegressionClassifier,
    stump_model: BaggedDecisionStumpEnsemble,
) -> pd.DataFrame:
    """Create a merged feature-importance artifact from both baselines."""

    rows: list[dict[str, Any]] = []

    if softmax_model.weights_ is None:
        raise ValueError("Softmax model has no weights")

    mean_abs = np.mean(np.abs(softmax_model.weights_), axis=1)
    for idx, feature_name in enumerate(feature_names):
        rows.append(
            {
                "model_name": "softmax_regression",
                "feature_name": feature_name,
                "importance": float(mean_abs[idx]),
                "class_label": "__all__",
                "signed_value": float(np.mean(softmax_model.weights_[idx, :])),
            }
        )

    for class_idx, class_label in enumerate(class_labels):
        for feat_idx, feature_name in enumerate(feature_names):
            coef = float(softmax_model.weights_[feat_idx, class_idx])
            rows.append(
                {
                    "model_name": "softmax_regression",
                    "feature_name": feature_name,
                    "importance": abs(coef),
                    "class_label": class_label,
                    "signed_value": coef,
                }
            )

    if stump_model.feature_importance_ is None:
        raise ValueError("Stump model has no feature importance")

    for idx, feature_name in enumerate(feature_names):
        rows.append(
            {
                "model_name": "bagged_stump_ensemble",
                "feature_name": feature_name,
                "importance": float(stump_model.feature_importance_[idx]),
                "class_label": "__all__",
                "signed_value": float(stump_model.feature_importance_[idx]),
            }
        )

    feature_importance_df = pd.DataFrame(rows)
    feature_importance_df = feature_importance_df.sort_values(
        ["model_name", "class_label", "importance", "feature_name"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)
    return feature_importance_df


def build_prediction_sample(
    prepared: PreparedDataset,
    models: dict[str, dict[str, Any]],
    best_model_name: str,
) -> pd.DataFrame:
    """Build audit-friendly prediction sample table from test split."""

    debug = prepared.debug_test.copy()

    idx_to_label = {idx: label for idx, label in enumerate(prepared.class_labels)}
    y_true_labels = [idx_to_label[idx] for idx in prepared.y_test]

    debug["true_label"] = y_true_labels

    for model_name, bundle in models.items():
        pred_labels = [idx_to_label[idx] for idx in bundle["predictions"]]
        debug[f"pred_label_{model_name}"] = pred_labels

        probs = bundle["probabilities"]
        for class_idx, class_label in enumerate(prepared.class_labels):
            debug[f"prob_{model_name}_{class_label}"] = probs[:, class_idx]

    debug["best_model_name"] = best_model_name
    debug["predicted_label"] = debug[f"pred_label_{best_model_name}"]
    debug["is_correct"] = debug["predicted_label"] == debug["true_label"]

    columns = [
        *(["uri"] if "uri" in debug.columns else []),
        *(["engagement_total"] if "engagement_total" in debug.columns else []),
        "true_label",
        "predicted_label",
        "best_model_name",
        "is_correct",
    ]
    for model_name in sorted(models.keys()):
        columns.append(f"pred_label_{model_name}")
        for class_label in prepared.class_labels:
            columns.append(f"prob_{model_name}_{class_label}")

    passthrough = [
        column
        for column in ["match_stage", "match_score", "has_trend_match", "candidate_count", "matched_candidate_count", "post_token_count", "actor_followers_count"]
        if column in debug.columns
    ]
    columns.extend(passthrough)

    ordered = [column for column in columns if column in debug.columns]
    return debug[ordered].copy().sort_values([ordered[0]] if ordered and ordered[0] == "uri" else ["true_label"], kind="stable").reset_index(drop=True)


def run_baseline_modeling(
    feature_df: pd.DataFrame,
    feature_summary: dict[str, Any] | None = None,
    config: ModelingConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """End-to-end orchestration for baseline modeling and artifacts."""

    cfg = _resolve_config(config)
    schema = inspect_feature_schema(feature_df)
    groups = build_column_groups(feature_df, feature_summary=feature_summary, target_column=TARGET_COLUMN)
    prepared = prepare_modeling_dataset(feature_df=feature_df, column_groups=groups, config=cfg)
    results = train_and_evaluate_baselines(prepared=prepared, config=cfg)

    return {
        "schema": schema,
        "column_groups": groups,
        "config": asdict(cfg),
        "results": results,
    }


def write_modeling_artifacts(
    modeling_output: dict[str, Any],
    output_dir: Path | str,
    sample_csv_path: Path | str,
) -> dict[str, str]:
    """Write required Phase 27 artifact files."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = out_dir / "baseline_model_metrics.json"
    importance_path = out_dir / "baseline_feature_importance.parquet"
    predictions_path = out_dir / "baseline_predictions_sample.parquet"
    summary_path = out_dir / "baseline_model_summary.json"
    confusion_path = out_dir / "baseline_confusion_matrix.csv"

    sample_csv = Path(sample_csv_path)
    sample_csv.parent.mkdir(parents=True, exist_ok=True)

    results = modeling_output["results"]
    metrics_payload = {
        "config": modeling_output["config"],
        "target_column": modeling_output["column_groups"]["target_column"],
        "model_feature_columns": results["model_feature_columns"],
        "excluded_columns": results["excluded_columns"],
        "split": results["split"],
        "best_model_name": results["best_model_name"],
        "best_model_criterion": results["best_model_criterion"],
        "models": results["models"],
    }
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    importance_df: pd.DataFrame = results["feature_importance"]
    importance_df.to_parquet(importance_path, index=False)

    prediction_df: pd.DataFrame = results["prediction_sample"]
    prediction_df.to_parquet(predictions_path, index=False)
    prediction_df.head(1000).to_csv(sample_csv, index=False)

    confusion_df: pd.DataFrame = results["confusion_matrix"]
    confusion_df.to_csv(confusion_path, index=True)

    summary_payload = {
        "schema": modeling_output["schema"],
        "column_groups": modeling_output["column_groups"],
        "config": modeling_output["config"],
        "best_model_name": results["best_model_name"],
        "best_model_criterion": results["best_model_criterion"],
        "models": results["models"],
        "split": results["split"],
        "artifact_paths": {
            "metrics_json": str(metrics_path),
            "feature_importance_parquet": str(importance_path),
            "prediction_sample_parquet": str(predictions_path),
            "prediction_sample_csv": str(sample_csv),
            "confusion_matrix_csv": str(confusion_path),
        },
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "metrics_json": str(metrics_path),
        "feature_importance_parquet": str(importance_path),
        "prediction_sample_parquet": str(predictions_path),
        "prediction_sample_csv": str(sample_csv),
        "summary_json": str(summary_path),
        "confusion_matrix_csv": str(confusion_path),
    }


def _resolve_config(config: ModelingConfig | dict[str, Any] | None) -> ModelingConfig:
    if config is None:
        return ModelingConfig()
    if isinstance(config, ModelingConfig):
        return config
    return ModelingConfig(**config)


def _fit_feature_encoder(df: pd.DataFrame) -> dict[str, Any]:
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []

    for column in df.columns:
        series = df[column]
        if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
            numeric_cols.append(column)
        else:
            categorical_cols.append(column)

    numeric_medians: dict[str, float] = {}
    numeric_means: dict[str, float] = {}
    numeric_stds: dict[str, float] = {}
    for column in numeric_cols:
        series = pd.to_numeric(df[column], errors="coerce")
        median = float(series.median()) if series.notna().any() else 0.0
        filled = series.fillna(median)
        mean = float(filled.mean())
        std = float(filled.std(ddof=0))
        if std <= 1e-12:
            std = 1.0
        numeric_medians[column] = median
        numeric_means[column] = mean
        numeric_stds[column] = std

    categorical_levels: dict[str, list[str]] = {}
    for column in categorical_cols:
        values = df[column].fillna("__MISSING__").astype(str)
        categorical_levels[column] = sorted(values.unique().tolist())

    feature_names: list[str] = []
    feature_names.extend([f"num__{column}" for column in numeric_cols])
    for column in categorical_cols:
        for level in categorical_levels[column]:
            feature_names.append(f"cat__{column}=={level}")

    return {
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
        "numeric_medians": numeric_medians,
        "numeric_means": numeric_means,
        "numeric_stds": numeric_stds,
        "categorical_levels": categorical_levels,
        "feature_names": feature_names,
    }


def _transform_with_encoder(df: pd.DataFrame, encoder: dict[str, Any]) -> np.ndarray:
    numeric_cols = encoder["numeric_cols"]
    categorical_cols = encoder["categorical_cols"]

    matrices: list[np.ndarray] = []

    if numeric_cols:
        num_mat = np.zeros((len(df), len(numeric_cols)), dtype=float)
        for idx, column in enumerate(numeric_cols):
            series = pd.to_numeric(df[column], errors="coerce").fillna(encoder["numeric_medians"][column])
            standardized = (series.to_numpy(dtype=float) - encoder["numeric_means"][column]) / encoder["numeric_stds"][column]
            num_mat[:, idx] = standardized
        matrices.append(num_mat)

    for column in categorical_cols:
        levels = encoder["categorical_levels"][column]
        values = df[column].fillna("__MISSING__").astype(str).to_numpy()
        mat = np.zeros((len(df), len(levels)), dtype=float)
        level_to_idx = {level: idx for idx, level in enumerate(levels)}
        for row_idx, value in enumerate(values):
            level_idx = level_to_idx.get(value)
            if level_idx is not None:
                mat[row_idx, level_idx] = 1.0
        matrices.append(mat)

    if not matrices:
        raise ValueError("No encoded features available")

    return np.concatenate(matrices, axis=1)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    denom = np.clip(np.sum(exp, axis=1, keepdims=True), 1e-12, None)
    return exp / denom


def _fit_best_stump(
    X_sample: np.ndarray,
    y_sample: np.ndarray,
    feature_idx: np.ndarray,
    n_classes: int,
    threshold_count: int,
) -> dict[str, Any]:
    parent_probs = _class_probs(y_sample, n_classes)
    parent_impurity = _gini(parent_probs)

    best = {
        "feature": -1,
        "threshold": 0.0,
        "left_probs": parent_probs,
        "right_probs": parent_probs,
        "default_probs": parent_probs,
        "gain": 0.0,
    }

    n = len(y_sample)
    for col in feature_idx:
        values = X_sample[:, col]
        if np.all(values == values[0]):
            continue

        thresholds = _candidate_thresholds(values, threshold_count)
        for threshold in thresholds:
            left_mask = values <= threshold
            right_mask = ~left_mask
            if not np.any(left_mask) or not np.any(right_mask):
                continue

            y_left = y_sample[left_mask]
            y_right = y_sample[right_mask]

            left_probs = _class_probs(y_left, n_classes)
            right_probs = _class_probs(y_right, n_classes)

            left_impurity = _gini(left_probs)
            right_impurity = _gini(right_probs)

            weighted = (len(y_left) / n) * left_impurity + (len(y_right) / n) * right_impurity
            gain = parent_impurity - weighted

            if gain > best["gain"]:
                best = {
                    "feature": int(col),
                    "threshold": float(threshold),
                    "left_probs": left_probs,
                    "right_probs": right_probs,
                    "default_probs": parent_probs,
                    "gain": float(gain),
                }

    return best


def _candidate_thresholds(values: np.ndarray, threshold_count: int) -> np.ndarray:
    unique = np.unique(values)
    if unique.size <= 1:
        return np.array([], dtype=float)

    if unique.size == 2:
        return np.array([(unique[0] + unique[1]) / 2.0], dtype=float)

    quantiles = np.linspace(0.05, 0.95, num=max(3, threshold_count))
    thresholds = np.quantile(values, quantiles)
    thresholds = np.unique(thresholds)
    return thresholds.astype(float)


def _class_probs(y: np.ndarray, n_classes: int) -> np.ndarray:
    counts = np.bincount(y, minlength=n_classes).astype(float)
    counts = counts + 1.0  # Laplace smoothing
    return counts / np.sum(counts)


def _gini(class_probs: np.ndarray) -> float:
    return float(1.0 - np.sum(np.square(class_probs)))


def _class_distribution(y: np.ndarray, class_labels: list[str]) -> dict[str, int]:
    counts = np.bincount(y, minlength=len(class_labels))
    return {class_labels[idx]: int(count) for idx, count in enumerate(counts)}


__all__ = [
    "BaggedDecisionStumpEnsemble",
    "ModelingConfig",
    "PreparedDataset",
    "SoftmaxRegressionClassifier",
    "build_column_groups",
    "build_feature_importance_table",
    "build_prediction_sample",
    "compute_classification_metrics",
    "inspect_feature_schema",
    "prepare_modeling_dataset",
    "run_baseline_modeling",
    "select_best_model_name",
    "stratified_train_test_split_indices",
    "train_and_evaluate_baselines",
    "write_modeling_artifacts",
]
