# 26 Local Feature Dictionary

Date: 2026-04-04

## Usage Notes
- Table grain: one row per Bluesky post `uri`
- Intended split:
  - modeling columns: `summary.feature_groups.model_feature_columns`
  - label columns: `engagement_*` + `engagement_label`
  - debug/reference columns: identifiers/raw text/source lineage

## Label Columns
| Column | Type | Source | Role |
|---|---|---|---|
| `engagement_label` | categorical (`LOW`/`MEDIUM`/`HIGH`) | derived from hydrated engagement | label |
| `engagement_total` | float | `eng_like_count + eng_reply_count + eng_repost_count + eng_quote_count` | label support |
| `eng_like_count` | float | hydrated posts | label component |
| `eng_reply_count` | float | hydrated posts | label component |
| `eng_repost_count` | float | hydrated posts | label component |
| `eng_quote_count` | float | hydrated posts | label component |

## Core Modeling Features
| Column | Type | Source | Role |
|---|---|---|---|
| `has_candidate` | bool | full-match candidate aggregate | model |
| `candidate_count` | int | full-match candidate aggregate | model |
| `matched_candidate_count` | int | full-match candidate aggregate | model |
| `matched_candidate_rate` | float | full-match candidate aggregate | model |
| `has_trend_match` | bool | best-match output | model |
| `match_stage` | categorical | best-match output | model |
| `match_score` | float | best-match output | model |
| `trend_counts` | float | best-match output | model |
| `trend_num_hours` | float | best-match output | model |
| `is_ambiguous_match` | bool | best-match output | model |
| `trend_date_available` | bool | best-match + parsed date | model |
| `trend_post_day_diff` | float | post/trend date comparison | model |
| `same_day_trend_match` | bool | post/trend date comparison | model |
| `post_token_count` | float | prepared posts | model |
| `post_char_count` | float | prepared posts | model |
| `post_unique_token_count` | float | derived from `post_text_alnum` | model |
| `post_unique_token_ratio` | float | derived from token counts | model |
| `raw_exclamation_count` | float | derived from `post_text_raw` | model |
| `raw_question_count` | float | derived from `post_text_raw` | model |
| `raw_uppercase_ratio` | float | derived from `post_text_raw` | model |
| `has_hashtag` | bool | prepared posts | model |
| `has_url` | bool | prepared posts | model |
| `has_mention` | bool | prepared posts | model |
| `has_special_chars` | bool | prepared posts | model |
| `has_non_ascii` | bool | prepared posts | model |
| `post_hour_utc` | float | parsed `post_created_at` | model |
| `post_day_of_week` | float | parsed `post_created_at` | model |
| `post_is_weekend` | bool | parsed `post_created_at` | model |
| `post_month` | float | parsed `post_created_at` | model |
| `actor_profile_found` | bool | actor join coverage | model |
| `actor_followers_count` | float | actor profiles | model |
| `actor_follows_count` | float | actor profiles | model |
| `actor_posts_count` | float | actor profiles | model |
| `actor_followers_to_follows_ratio` | float | derived actor ratio | model |
| `actor_has_display_name` | bool | actor profiles | model |
| `actor_has_description` | bool | actor profiles | model |
| `actor_description_char_count` | float | actor profiles | model |
| `actor_has_avatar` | bool | actor profiles | model |
| `actor_has_banner` | bool | actor profiles | model |

## Debug and Reference Columns (Not for Modeling)
Representative debug/reference fields retained for auditability:
- identifiers: `uri`, `hydrated_author_did`, `hydrated_author_handle`, `actor_did`, `actor_handle`
- source lineage: `source_run_tag`, `text_source`, hydrated/actor run ids and timestamps
- text traceability: `post_text_raw`, `post_text_clean`, `post_text_alnum`
- trend traceability: `trend_name_clean`, `trend_date`, `match_method`, `temporal_pool_mode`

Raw JSON lineage fields are retained in the feature table but excluded from model feature groups.
