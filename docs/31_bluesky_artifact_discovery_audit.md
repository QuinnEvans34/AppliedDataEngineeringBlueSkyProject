# 31 Bluesky Artifact Discovery Audit

Date: 2026-04-04  
Mode: read-only workspace inspection (no Snowflake, no reruns)

## Executive Summary
- The larger Bluesky corpus is present in workspace, but **outside the repo tree**:
  - `../snowflake_package - Copy`
- Confirmed totals in that package:
  - `raw_posts`: `19,994` rows
  - `hydrated_posts`: `19,731` rows
  - `actor_profiles`: `13,850` rows
- The repo-local `data/` tree only contains small diagnostic subsets (`25`/`25`/`21`).
- This explains why downstream local phases used only ~25 posts.

---

## 1) All Relevant `.jsonl.gz` Files Found

### A. Repo-local files (`./data/...`)
| Path | Family | Size (bytes) | Row Count | Run-root Context |
|---|---|---:|---:|---|
| `data/phase6_diagnostic_20260401/raw_posts/cap_20260401T184939Z_85c99020/raw_posts_000001.jsonl.gz` | raw_posts | 6,292 | 25 | `data/phase6_diagnostic_20260401` |
| `data/phase6_diagnostic_20260401/hydrated_posts/hyd_20260401T185109Z_97b40e6f/hydrated_posts_000001.jsonl.gz` | hydrated_posts | 6,658 | 25 | `data/phase6_diagnostic_20260401` |
| `data/phase5_actor_validation_20260401/actor_profiles/act_20260401T231425Z_48569e45/actor_profiles_000001.jsonl.gz` | actor_profiles | 8,041 | 21 | `data/phase5_actor_validation_20260401` |
| `data/hydrated_posts/hyd_20260401T182525Z_c92b3e88/hydrated_posts_000001.jsonl.gz` | hydrated_posts | 429 | 2 | `data` (scratch root) |
| `data/hydration_misses/hyd_20260401T182525Z_c92b3e88/hydration_misses_000001.jsonl.gz` | hydration_misses | 284 | 1 | `data` (scratch root) |

### B. Workspace sibling files (`../snowflake_package - Copy/...`)
| Path | Family | Size (bytes) | Row Count | Run-root Context |
|---|---|---:|---:|---|
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000001.jsonl.gz` | raw_posts | 898,805 | 3,128 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000002.jsonl.gz` | raw_posts | 941,057 | 3,281 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000003.jsonl.gz` | raw_posts | 891,661 | 3,078 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000004.jsonl.gz` | raw_posts | 1,021,879 | 3,560 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000005.jsonl.gz` | raw_posts | 917,938 | 3,228 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000006.jsonl.gz` | raw_posts | 934,906 | 3,293 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/raw_posts/cap_20260402T181311Z_f98d0c5f/raw_posts_000007.jsonl.gz` | raw_posts | 124,901 | 426 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000001.jsonl.gz` | hydrated_posts | 2,611,155 | 8,975 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000002.jsonl.gz` | hydrated_posts | 2,759,126 | 9,597 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/hydrated_posts/hyd_20260402T181936Z_5cf8bb07/hydrated_posts_000003.jsonl.gz` | hydrated_posts | 334,878 | 1,159 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/actor_profiles/act_20260402T182221Z_1784be30/actor_profiles_000001.jsonl.gz` | actor_profiles | 3,425,365 | 9,873 | `../snowflake_package - Copy` |
| `../snowflake_package - Copy/actor_profiles/act_20260402T182221Z_1784be30/actor_profiles_000002.jsonl.gz` | actor_profiles | 1,362,369 | 3,977 | `../snowflake_package - Copy` |

Schema spot-checks (confirmed):
- raw row has keys like: `uri`, `repo_did`, `record_created_at`, `record`, `capture_run_id`, `captured_at`
- hydrated row has keys like: `uri`, `author_did`, `author_handle`, `like_count`, `reply_count`, `repost_count`, `quote_count`, `record`
- actor row has keys like: `did`, `handle`, `followers_count`, `follows_count`, `posts_count`, `profile`, `actor_run_id`

---

## 2) Run-Root Grouping and Coverage

| Run Root | Families Present | Files per Family | Approx Rows per Family | Classification |
|---|---|---|---|---|
| `data/phase6_diagnostic_20260401` | raw, hydrated | raw:1 hydrated:1 | raw:25 hydrated:25 | tiny diagnostic subset |
| `data/phase5_actor_validation_20260401` | actor | actor:1 | actor:21 | tiny partial run |
| `data` | hydrated, hydration_misses | hydrated:1 misses:1 | hydrated:2 misses:1 | tiny scratch subset |
| `data/output/phase9_configcheck_20260402_095603` | family dirs exist but empty | all:0 | all:0 | config-check shell only |
| `../snowflake_package - Copy` | raw, hydrated, actor | raw:7 hydrated:3 actor:2 | raw:19,994 hydrated:19,731 actor:13,850 | full usable run (for local scaling) |

Confirmed family totals for `../snowflake_package - Copy`:
- raw: `7` files, `19,994` rows
- hydrated: `3` files, `19,731` rows
- actor: `2` files, `13,850` rows

---

## 3) Likely Snowflake-Loaded Source (~20k)

### Confirmed facts
- The only workspace location with ~20k-scale raw/hydrated and ~13k actor `.jsonl.gz` is:
  - `../snowflake_package - Copy`
- Folder structure is staging-compatible for loader family discovery:
  - `raw_posts/<capture_run_id>/raw_posts_*.jsonl.gz`
  - `hydrated_posts/<hydrate_run_id>/hydrated_posts_*.jsonl.gz`
  - `actor_profiles/<actor_run_id>/actor_profiles_*.jsonl.gz`
- Exact counts strongly match expected corpus scale:
  - raw `19,994` (near 20k)
  - hydrated `19,731` (near 20k)
  - actor `13,850` (near 13k)

### Inference
- **Most likely Snowflake-loaded source** is `../snowflake_package - Copy`.
- Confidence is high due row counts + naming + structure; no competing ~20k candidate exists in searched workspace paths.

---

## 4) Why Previous Audit Surfaced Only ~25 Rows

### Confirmed causes
1. Earlier audit scope focused on repo-local trees (`data/`, `local/`, repo root), where only diagnostic files exist.
2. Larger corpus is in a sibling workspace directory (`../snowflake_package - Copy`), outside repo path.
3. Phase 23 notebook/code explicitly searches `base_dir="data"`:
   - it cannot discover sibling run roots unless base path is changed.
4. Downstream phases 24–27 consume outputs from phase 23; once phase 23 starts at 25 rows, the rest remain small.

### Not observed
- No evidence of hardcoded 25-row truncation in phase logic.
- No evidence that sample files were mistakenly used as primary phase inputs.

---

## 5) Recommended Downstream Source Path

### Recommended source root
- Use: `../snowflake_package - Copy`

### Coverage sufficiency there
- raw/hydrated/actor coverage is sufficient for a full local rerun of phases 23–27 at intended scale.
- hydration_misses are not included in that package (not required for phases 23–27 inputs).

### Can we rerun phases 23–27 now?
- **Yes, with path repointing.**
- Important operational note:
  - Current notebooks/functions default to `base_dir="data"` for source discovery in phase 23/26 selectors.
  - To use the larger corpus immediately, run with `base_dir="../snowflake_package - Copy"` (or mirror/symlink package into repo `data/` hierarchy before rerun).

---

## Final Answers

### Where real larger Bluesky files are
- `../snowflake_package - Copy` (workspace sibling folder to repo).

### Which run root likely produced Snowflake load
- `../snowflake_package - Copy` (high-confidence; counts and structure match expected load scale).

### Why earlier audit missed them
- Search scope was repo-local; larger corpus sits outside repo tree and phase discovery defaults to `data/`.

### Exact path downstream should use next
- `../snowflake_package - Copy`

### Ready to rerun phases 23–27 on larger corpus?
- Yes, if source discovery base path is pointed at that run root (or the run root is staged under repo `data/`).
