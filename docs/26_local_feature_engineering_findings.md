# 26 Local Feature Engineering Findings

Date: 2026-04-04

## Scope
- Phase spec: `docs/26_local_feature_engineering.md`
- Mode: local-only (`0` Snowflake queries, `0` collection/enrichment reruns)
- This phase builds an ML-ready local feature table only (no model training)

## Inputs and Actual Schemas Used
Primary inputs:
- `local/derived/bluesky/bluesky_posts_prepared.parquet`
- `local/derived/matching/bluesky_post_best_trend_matches.parquet`
- `local/derived/matching/bluesky_post_trend_matches.parquet`

Selected local engagement and actor sources (deterministic selection):
- Hydrated source: `data/phase6_diagnostic_20260401/hydrated_posts/hyd_20260401T185109Z_97b40e6f/hydrated_posts_000001.jsonl.gz`
- Actor source: `data/phase5_actor_validation_20260401/actor_profiles/act_20260401T231425Z_48569e45/actor_profiles_000001.jsonl.gz`

Key fields used across joins:
- Post/base: `uri`, `post_created_at`, `post_text_*`, `post_token_count`, `post_char_count`, text flags, `hydrated_author_did`
- Best-match: `match_stage`, `match_score`, `match_method`, `temporal_pool_mode`, `trend_name_clean`, `trend_date`, `trend_counts`, `trend_num_hours`, `is_matched`, `is_ambiguous`
- Full-match aggregates: `uri`, `candidate_id`, `is_matched`
- Hydrated engagement: `uri`, `author_did`, `author_handle`, `like_count`, `reply_count`, `repost_count`, `quote_count`
- Actor/account: `did`, `handle`, `followers_count`, `follows_count`, `posts_count`, `display_name`, `description`, `has_avatar`, `has_banner`

## Feature-Table Grain and Join Strategy
Feature-table grain:
- **one row per Bluesky post `uri`** from prepared posts

Join strategy (all left joins from prepared base):
1. prepared posts -> best match by `uri`
2. + candidate aggregates from full matches by `uri`
3. + hydrated metrics by `uri`
4. + actor profile by `hydrated_author_did == did`

Join coverage:
- prepared -> best match: `19/25` matched (`76.0%`), `6` left-only
- + candidate aggregates: `19/25` matched (`76.0%`), `6` left-only
- + hydrated metrics: `25/25` matched (`100.0%`)
- + actor profiles: `25/25` matched (`100.0%`)

## Engagement Target Construction
Engagement components (null-safe numeric):
- `eng_like_count`, `eng_reply_count`, `eng_repost_count`, `eng_quote_count`

Aggregate:
- `engagement_total = like + reply + repost + quote`

Primary label rule:
- quantile thresholds at `q33` and `q66`
- `LOW <= q33`, `MEDIUM <= q66`, `HIGH > q66`

Observed thresholds in this run:
- `q33 = 0.0`
- `q66 = 0.84`

Applied fallback rule (deterministic):
- rule mode: `fallback_count_bins`
- reason: `collapsed_quantile_or_empty_class`
- fallback bins: `LOW == 0`, `MEDIUM == 1`, `HIGH >= 2`

Final label distribution:
- `LOW: 16`
- `MEDIUM: 5`
- `HIGH: 4`

## Major Feature Groups Created
Trend-match features:
- `has_candidate`, `has_trend_match`, `match_stage`, `match_score`
- `trend_counts`, `trend_num_hours`, `is_ambiguous_match`
- `trend_date_available`, `trend_post_day_diff`, `same_day_trend_match`
- `candidate_count`, `matched_candidate_count`, `matched_candidate_rate`

Post-text features:
- existing prepared signals: `post_token_count`, `post_char_count`, `has_hashtag`, `has_url`, `has_mention`, `has_special_chars`, `has_non_ascii`
- derived: `post_unique_token_count`, `post_unique_token_ratio`, `raw_exclamation_count`, `raw_question_count`, `raw_uppercase_ratio`

Actor/account features:
- `actor_profile_found`
- `actor_followers_count`, `actor_follows_count`, `actor_posts_count`
- `actor_followers_to_follows_ratio`
- `actor_has_display_name`, `actor_has_description`, `actor_description_char_count`, `actor_has_avatar`, `actor_has_banner`

Temporal features:
- `post_hour_utc`, `post_day_of_week`, `post_is_weekend`, `post_month`

## Data Quality, Missingness, and Leakage Controls
Feature table size:
- rows: `25`
- columns: `92`
- model feature columns: `67`

Missingness highlights:
- largest model-feature missingness: `is_ambiguous` and `is_matched` (`6` rows each), corresponding to posts with no candidate-level matching rows
- most other engineered numeric/boolean features: no missing values after explicit null handling

Match-stage distribution:
- `unmatched: 13`
- `no_candidate: 6`
- `semantic: 4`
- `fuzzy: 2`
- `exact: 0`

Leakage guardrails implemented:
- label/target components are excluded from model feature list:
  - `engagement_label`
  - `engagement_total`
  - `eng_like_count`, `eng_reply_count`, `eng_repost_count`, `eng_quote_count`
- debug/reference columns are tracked separately from model features

## Outputs Written
- `src/features/feature_engineering.py`
- `tests/test_feature_engineering.py`
- `notebooks/26_local_feature_engineering.ipynb`
- `local/derived/features/bluesky_engagement_features.parquet`
- `data/samples/bluesky_engagement_features_sample_1000.parquet`
- `data/samples/bluesky_engagement_features_sample_1000.csv`
- `local/derived/features/bluesky_engagement_feature_summary.json` (optional)

## Limitations
- Dataset is small (`25` posts), so feature/label stability is limited.
- Trend-date alignment remains weak from prior phase date mismatch; trend timing features are present but not strongly informative in this slice.
- Match signal sparsity remains high (`unmatched` + `no_candidate` dominates), which may cap baseline model performance.

## Readiness for Phase 27
Ready for Phase 27 baseline ML modeling: **YES, with caveats**.

Reason:
- deterministic, auditable local feature engineering is implemented and tested
- joins, target rule, and feature groups are documented with measured coverage
- leakage controls and model/debug/label separation are explicit

Caveat:
- small sample size and sparse match signals require careful baseline evaluation and likely iterative threshold/feature refinement.
