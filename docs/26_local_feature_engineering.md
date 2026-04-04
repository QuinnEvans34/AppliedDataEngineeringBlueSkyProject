# 26 — Local Feature Engineering

## Objective
Build a local, reproducible, ML-ready feature dataset for Bluesky engagement prediction using:
- matched Twitter trend signals
- prepared Bluesky post text features
- hydrated engagement metrics
- actor/account features where available

This phase is local-only.

## Why this phase exists
Phase 25 produced structured post-to-trend matches.
The next step is to convert the locally available post, match, hydration, and account data into a clean feature table that can be used in the baseline ML phase.

This phase should produce a documented training dataset.
It should not train the model yet.

## Hard constraints
- Use ZERO Snowflake queries
- Do NOT rerun the Bluesky firehose
- Do NOT rerun hydration
- Do NOT rerun actor/profile enrichment
- Do NOT create new collection runs
- Do NOT modify raw source files in place
- Keep all work local and reproducible
- Keep feature engineering explicit, auditable, and testable
- Preserve enough raw/reference columns for debugging, but avoid bloated outputs
- Do NOT train ML yet

## Required context to read first
Before implementing anything, read:

- `docs/25_local_post_to_trend_matching.md`
- `docs/25_local_post_to_trend_matching_findings.md`
- `docs/24_local_topic_extraction_candidate_generation_findings.md`
- `docs/23_local_bluesky_text_preparation_findings.md`
- `docs/22_local_twitter_trend_normalization_findings.md`

Also inspect the actual local schemas of all candidate input datasets before writing logic.

## Inputs
Primary local inputs may include:

- `local/derived/matching/bluesky_post_best_trend_matches.parquet`
- `local/derived/matching/bluesky_post_trend_matches.parquet`
- `local/derived/bluesky/bluesky_posts_prepared.parquet`

Also inspect the best available local Bluesky source data for:
- hydrated engagement metrics
- actor/account metadata
- record identifiers needed for joins

Likely sources may include local outputs or prior run-root families such as:
- `hydrated_posts/`
- `actor_profiles/`

Use the already-collected local data only.
Do not fetch anything new.

## Deliverables
Create:

- `src/features/feature_engineering.py`
- `notebooks/26_local_feature_engineering.ipynb`
- `docs/26_local_feature_engineering_findings.md`
- `tests/test_feature_engineering.py`

Create local outputs:

- `local/derived/features/bluesky_engagement_features.parquet`
- `data/samples/bluesky_engagement_features_sample_1000.parquet`
- `data/samples/bluesky_engagement_features_sample_1000.csv`

Optional but preferred if useful:
- `local/derived/features/bluesky_engagement_feature_summary.json`
- `docs/26_local_feature_dictionary.md`

## Required implementation behavior

### 1. Inspect and document actual schemas used
Inspect the actual schemas of the available local inputs and document:
- post identifier field(s)
- text field(s)
- timestamp/date field(s)
- trend-match field(s)
- engagement metric field(s)
- actor/account field(s)
- join keys actually available across datasets

Do not assume field names blindly.
Use the actual local outputs and source schemas.

### 2. Define and document the grain of the feature table
Choose and document the feature-table grain explicitly.

Default expectation:
- one row per Bluesky post

If the available local data makes a different grain necessary, document why.
Do not leave grain implicit.

### 3. Join strategy must be explicit
Implement an explicit local join strategy across:
- prepared Bluesky post data
- best-match trend data
- hydrated engagement metrics
- actor/account features where available

Requirements:
- document which joins are inner vs left joins
- document join coverage and drop-off at each step
- do not silently discard large amounts of data
- if some datasets do not join cleanly, preserve the maximum usable local dataset and document the limitation clearly

### 4. Engagement target construction
Create a documented engagement target suitable for the later baseline classifier.

Requirements:
- inspect the actual hydrated engagement fields available
- define a reproducible aggregate engagement metric if needed
- create a LOW / MEDIUM / HIGH engagement label
- document the rule used to assign labels

Preferred approach:
- use quantile-based bucketing unless the observed data strongly supports a better explicit threshold strategy

Requirements for labeling:
- deterministic
- reproducible
- documented in notebook and findings
- preserve the raw engagement components and aggregate metric where useful

### 5. Feature categories to build
Build a practical baseline feature set from the local data.

At minimum consider and implement where supported by actual data:

#### A. Trend-match features
Examples:
- has trend match
- match stage (`exact`, `fuzzy`, `semantic`)
- numeric match score
- matched trend count/volume if available
- matched trend duration/num_hours if available
- ambiguity flag if available
- same-day match flag if date fields support it

#### B. Post text features
Examples:
- prepared text length
- token count
- character count
- hashtag count
- mention count
- URL count
- punctuation/exclamation/question counts where useful
- uppercase ratio only if raw text makes it meaningful
- candidate count from Phase 24 if available
- unique token count if easy to compute cleanly

#### C. Actor/account features
Examples where available:
- follower/following counts
- account/profile completeness indicators
- actor metadata presence flag
- other lightweight numeric/profile fields present locally

Do not invent features that are not supported by actual local schema.

#### D. Temporal features
Examples where supported:
- posting hour
- day of week
- weekend flag
- month/day features if useful
- trend-date alignment flags

Only build temporal features if usable timestamps actually exist.

### 6. Data cleaning for ML readiness
Produce a feature table suitable for baseline modeling.

Requirements:
- clear handling of missing values
- explicit typing for numeric/categorical/boolean features
- avoid leaking target information into features
- avoid keeping obviously unusable high-cardinality raw identifiers as model features
- preserve a separate set of debug/reference columns where helpful

Important:
Do not leak post-hydration target values back into explanatory features in a circular way beyond the intended label construction.

### 7. Feature selection output structure
The main output parquet should include:
- stable post identifier
- target label (`LOW`, `MEDIUM`, `HIGH`)
- raw engagement aggregate used for labeling
- engineered feature columns
- limited debug/reference columns needed for auditability

The output should be easy to separate into:
- modeling columns
- label columns
- debug/reference columns

Use stable and explicit column names.

### 8. Coverage and quality profiling
Measure and document at minimum:
- initial post count
- counts after each join step
- labeled row count
- label distribution
- missingness by feature
- numeric feature summary stats
- categorical feature cardinality summary
- features dropped or excluded and why
- any major sparsity or leakage risks identified

### 9. Notebook requirements
The notebook should:
- inspect actual input schemas
- explain the chosen grain and join strategy
- show join coverage step by step
- explain target-label construction
- summarize major feature groups created
- show missingness and feature-quality summaries
- call out leakage risks or limitations
- end with a clear statement on readiness for baseline ML

Keep it readable and concise.

### 10. Findings markdown
Write:
- `docs/26_local_feature_engineering_findings.md`

It should summarize:
- actual schemas/fields used
- grain and join strategy
- target-label construction rule
- major feature groups created
- join coverage outcomes
- label distribution
- missingness / sparsity concerns
- leakage concerns avoided
- known limitations
- whether the project is ready for Phase 27 baseline ML modeling

### 11. Optional feature dictionary
If implemented, write:
- `docs/26_local_feature_dictionary.md`

This should briefly describe:
- each engineered feature
- type
- source
- whether it is intended for modeling or only debugging/reference

## Suggested module structure
`src/features/feature_engineering.py` should expose small readable functions.

Suggested structure:
- schema inspection helper(s)
- engagement aggregate / label construction helper
- feature builders by category
- join/orchestration helper
- final dataset assembly helper

Keep it simple.
Do not build a framework.

## Testing requirements
Create tests for:
- engagement aggregate construction
- LOW/MEDIUM/HIGH label assignment
- join behavior for partial/missing local inputs
- match-feature derivation
- text-feature derivation
- missing-value handling
- leakage guardrails where practical
- deterministic output on repeated runs
- several real edge cases discovered from the local schemas/data

Tests should validate both correctness and reproducibility.

## Non-goals
This phase should NOT:
- touch Snowflake
- rerun any Bluesky collection/enrichment job
- train the model
- tune hyperparameters
- build Tableau outputs yet

## Definition of done
This phase is done when:
1. reusable feature-engineering logic exists in `src/features/feature_engineering.py`
2. an ML-ready local feature dataset is written
3. tests cover target construction, joins, and core feature derivations
4. notebook and markdown findings document exactly how the feature set was built
5. the project is ready to move into baseline ML modeling