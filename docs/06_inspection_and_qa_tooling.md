# Phase 6: Inspection and QA Tooling

## Purpose

This phase adds practical tooling so the pipeline output can be inspected directly by a human, without relying on markdown summaries or manually decompressing files every time.

The goal is **not** to replace the canonical dataset format.

The canonical pipeline output should remain:
- `.jsonl.gz` for raw posts
- `.jsonl.gz` for hydrated posts
- `.jsonl.gz` for actor profiles
- `.jsonl.gz` for misses if used

This phase adds utilities for:
- viewing rows directly
- exporting small readable samples
- validating schema shape
- checking row counts and null rates
- confirming that the data being captured is real and usable

This phase is about **inspection and QA only**.

Do not redesign the pipeline outputs in this phase.

---

## Why this phase exists

The current pipeline format is correct for staging and loading, but it is not convenient for manual inspection during development.

You need a way to:
- open and inspect real rows
- confirm required fields are present
- verify tags/facets/reply/embed behavior
- verify author enrichment is present
- verify engagement fields are present
- catch broken output before loading into Snowflake

This phase should give that visibility without changing the real storage format.

---

## Scope of this phase

### In scope
- inspection utilities for `.jsonl.gz` pipeline outputs
- sample export utilities
- schema-validation utilities
- quick stats / profiling utilities
- row-level pretty-printing
- dataset-level sanity checks
- optional manifest / summary file generation

### Out of scope
- no Snowflake SQL
- no pipeline redesign
- no firehose redesign
- no hydration redesign
- no actor-enrichment redesign
- no model training
- no news enrichment

---

## End state for this phase

At the end of Phase 6, the project should provide simple tools or commands that can:

1. list dataset files
2. inspect the first or last N rows of a dataset
3. pretty-print one or more rows for readability
4. export a small sample from `.jsonl.gz` to plain `.jsonl` or pretty `.json`
5. validate required fields for each dataset type
6. compute quick QA stats for a dataset
7. help confirm the weekend run produced usable data

---

## Canonical format must remain unchanged

The pipeline should continue to write:

- `raw_posts/*.jsonl.gz`
- `hydrated_posts/*.jsonl.gz`
- `actor_profiles/*.jsonl.gz`
- optional misses as `.jsonl.gz`

Do **not** replace this with:
- giant `.json` arrays
- CSV as the canonical format
- uncompressed-only storage
- format-specific hacks for inspection

The inspection layer should be additive, not destructive.

---

## Tooling goals

This phase should create human-usable inspection tools for four practical needs:

### 1. direct row inspection
Open a dataset and inspect real rows without manually decompressing files.

### 2. sample export
Export a small number of rows into a plain readable format for manual review.

### 3. schema validation
Check that each dataset has the fields it is supposed to have.

### 4. quick profiling
Get fast sanity metrics such as:
- row counts
- null counts
- missing required field counts
- simple value distributions for key fields

---

## Datasets to support

The inspection tooling should support at least these dataset families:

- raw posts
- hydrated posts
- actor profiles
- hydration misses if they exist

Each tool should either:
- auto-detect dataset type from path or row shape
- or accept a dataset type argument explicitly

Keep the implementation simple.

---

## Suggested project structure

Codex may add a new package such as:

```text
bluesky_pipeline/
  inspect/
    __init__.py
    reader.py
    viewer.py
    exporter.py
    validator.py
    profiler.py

# Phase 6: Inspection and QA Tooling

## Purpose

This phase adds practical tooling so the pipeline output can be inspected directly by a human, without relying on markdown summaries or manually decompressing files every time.

The goal is **not** to replace the canonical dataset format.

The canonical pipeline output should remain:
- `.jsonl.gz` for raw posts
- `.jsonl.gz` for hydrated posts
- `.jsonl.gz` for actor profiles
- `.jsonl.gz` for misses if used

This phase adds utilities for:
- viewing rows directly
- exporting small readable samples
- validating schema shape
- checking row counts and null rates
- confirming that the data being captured is real and usable

This phase is about **inspection and QA only**.

Do not redesign the pipeline outputs in this phase.

---

## Why this phase exists

The current pipeline format is correct for staging and loading, but it is not convenient for manual inspection during development.

You need a way to:
- open and inspect real rows
- confirm required fields are present
- verify tags/facets/reply/embed behavior
- verify author enrichment is present
- verify engagement fields are present
- catch broken output before loading into Snowflake

This phase should give that visibility without changing the real storage format.

---

## Scope of this phase

### In scope
- inspection utilities for `.jsonl.gz` pipeline outputs
- sample export utilities
- schema-validation utilities
- quick stats / profiling utilities
- row-level pretty-printing
- dataset-level sanity checks
- optional manifest / summary file generation

### Out of scope
- no Snowflake SQL
- no pipeline redesign
- no firehose redesign
- no hydration redesign
- no actor-enrichment redesign
- no model training
- no news enrichment

---

## End state for this phase

At the end of Phase 6, the project should provide simple tools or commands that can:

1. list dataset files
2. inspect the first or last N rows of a dataset
3. pretty-print one or more rows for readability
4. export a small sample from `.jsonl.gz` to plain `.jsonl` or pretty `.json`
5. validate required fields for each dataset type
6. compute quick QA stats for a dataset
7. help confirm the weekend run produced usable data

---

## Canonical format must remain unchanged

The pipeline should continue to write:

- `raw_posts/*.jsonl.gz`
- `hydrated_posts/*.jsonl.gz`
- `actor_profiles/*.jsonl.gz`
- optional misses as `.jsonl.gz`

Do **not** replace this with:
- giant `.json` arrays
- CSV as the canonical format
- uncompressed-only storage
- format-specific hacks for inspection

The inspection layer should be additive, not destructive.

---

## Tooling goals

This phase should create human-usable inspection tools for four practical needs:

### 1. direct row inspection
Open a dataset and inspect real rows without manually decompressing files.

### 2. sample export
Export a small number of rows into a plain readable format for manual review.

### 3. schema validation
Check that each dataset has the fields it is supposed to have.

### 4. quick profiling
Get fast sanity metrics such as:
- row counts
- null counts
- missing required field counts
- simple value distributions for key fields

---

## Datasets to support

The inspection tooling should support at least these dataset families:

- raw posts
- hydrated posts
- actor profiles
- hydration misses if they exist

Each tool should either:
- auto-detect dataset type from path or row shape
- or accept a dataset type argument explicitly

Keep the implementation simple.

---

## Suggested project structure

Codex may add a new package such as:

```text
bluesky_pipeline/
  inspect/
    __init__.py
    reader.py
    viewer.py
    exporter.py
    validator.py
    profiler.py

And one or more entrypoints such as:
bluesky_pipeline/
  main_inspect.py
  main_export.py
  main_validate.py
A single CLI entrypoint is also acceptable if it remains readable.
The exact layout can vary slightly, but responsibilities should stay separated.