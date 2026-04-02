# Phase 5: Actor Enrichment Implementation

## Purpose

This phase adds a third dataset to the pipeline:

- **actor profiles / author enrichment**

The goal is to collect author-level metadata for the posts already captured and hydrated, so the downstream machine learning dataset is not limited to post text and post structure alone.

By the end of this phase, the project should be able to:

- identify unique authors from the captured/hydrated datasets
- batch author lookups using the public Bluesky profile endpoint
- collect profile-level metadata such as follower count, follows count, posts count, and basic profile fields
- write a separate local actor-enrichment dataset as rotating `.jsonl.gz`
- preserve clean join keys for Snowflake
- make reruns safe and idempotent

This phase is about **author/profile enrichment only**.

Do not redesign the firehose or hydration paths in this phase.

---

## Why this phase exists

The current pipeline gives us:

1. **raw posts**
   - text
   - timestamps
   - structural post metadata
   - tags/facets/reply/embed information

2. **hydrated posts**
   - engagement counts after the maturity window
   - some author metadata from the post view

That is enough for a baseline model, but it is weak if we want stronger predictive power.

The most important missing feature family is **author reach / profile context**, especially:
- follower count
- follows count
- posts count
- profile metadata

This phase creates that dataset cleanly and separately.

---

## Scope of this phase

### In scope
- implement the public actor/profile enrichment client
- add a job that reads unique authors and enriches them
- batch actor lookups safely
- write a separate actor dataset
- track actor-enrichment state in SQLite
- keep reruns safe and idempotent
- add logging, retry, and clean shutdown behavior

### Out of scope
- no Snowflake SQL
- no warehouse joins
- no model training
- no firehose redesign
- no hydration redesign except small compatibility fixes if truly necessary
- no news enrichment yet
- no uploader/cloud logic

---

## End state for this phase

At the end of Phase 5, the project should be able to run an actor-enrichment job that:

1. identifies authors that need enrichment
2. batches them into valid public profile requests
3. fetches profile metadata from Bluesky
4. normalizes one actor row per DID
5. writes actor rows into local rotating `.jsonl.gz` files
6. tracks enrichment state safely in SQLite
7. can rerun without duplicating work

---

## Data source

Use the public Bluesky profile lookup endpoint for multiple actors.

The implementation should support the public profile lookup flow for multiple DIDs/actors in one request.

The system should batch requests conservatively and treat profile enrichment as read-only public API usage.

---

## High-level enrichment flow

The actor-enrichment pipeline should follow this structure:

1. determine the source of author DIDs
2. select unique authors that are not yet enriched
3. batch DIDs into request-size chunks
4. call the public profile lookup endpoint
5. normalize returned profile rows
6. write actor rows to the actor dataset
7. mark enriched actors in SQLite
8. mark unresolved actors as retryable or failed based on retry policy
9. continue until no pending authors remain

---

## Which authors to enrich

For the first implementation, the actor-enrichment job should work from **captured/hydrated post authors**, not from arbitrary external actor lists.

### Preferred source
Use author DIDs derived from the pipeline data already collected.

The cleanest options are:

1. **preferred**
   - derive unique author DIDs from the hydrated dataset or hydrated-state records

2. **acceptable fallback**
   - derive unique author DIDs from the captured post dataset if needed

The key requirement is:
- one enriched actor row per unique DID

---

## Dataset design

This phase creates a new dataset:

```text
data/
  actor_profiles/
    <actor_run_id>/
      actor_profiles_000001.jsonl.gz
      actor_profiles_000002.jsonl.gz

# Phase 5: Actor Enrichment Implementation

## Purpose

This phase adds a third dataset to the pipeline:

- **actor profiles / author enrichment**

The goal is to collect author-level metadata for the posts already captured and hydrated, so the downstream machine learning dataset is not limited to post text and post structure alone.

By the end of this phase, the project should be able to:

- identify unique authors from the captured/hydrated datasets
- batch author lookups using the public Bluesky profile endpoint
- collect profile-level metadata such as follower count, follows count, posts count, and basic profile fields
- write a separate local actor-enrichment dataset as rotating `.jsonl.gz`
- preserve clean join keys for Snowflake
- make reruns safe and idempotent

This phase is about **author/profile enrichment only**.

Do not redesign the firehose or hydration paths in this phase.

---

## Why this phase exists

The current pipeline gives us:

1. **raw posts**
   - text
   - timestamps
   - structural post metadata
   - tags/facets/reply/embed information

2. **hydrated posts**
   - engagement counts after the maturity window
   - some author metadata from the post view

That is enough for a baseline model, but it is weak if we want stronger predictive power.

The most important missing feature family is **author reach / profile context**, especially:
- follower count
- follows count
- posts count
- profile metadata

This phase creates that dataset cleanly and separately.

---

## Scope of this phase

### In scope
- implement the public actor/profile enrichment client
- add a job that reads unique authors and enriches them
- batch actor lookups safely
- write a separate actor dataset
- track actor-enrichment state in SQLite
- keep reruns safe and idempotent
- add logging, retry, and clean shutdown behavior

### Out of scope
- no Snowflake SQL
- no warehouse joins
- no model training
- no firehose redesign
- no hydration redesign except small compatibility fixes if truly necessary
- no news enrichment yet
- no uploader/cloud logic

---

## End state for this phase

At the end of Phase 5, the project should be able to run an actor-enrichment job that:

1. identifies authors that need enrichment
2. batches them into valid public profile requests
3. fetches profile metadata from Bluesky
4. normalizes one actor row per DID
5. writes actor rows into local rotating `.jsonl.gz` files
6. tracks enrichment state safely in SQLite
7. can rerun without duplicating work

---

## Data source

Use the public Bluesky profile lookup endpoint for multiple actors.

The implementation should support the public profile lookup flow for multiple DIDs/actors in one request.

The system should batch requests conservatively and treat profile enrichment as read-only public API usage.

---

## High-level enrichment flow

The actor-enrichment pipeline should follow this structure:

1. determine the source of author DIDs
2. select unique authors that are not yet enriched
3. batch DIDs into request-size chunks
4. call the public profile lookup endpoint
5. normalize returned profile rows
6. write actor rows to the actor dataset
7. mark enriched actors in SQLite
8. mark unresolved actors as retryable or failed based on retry policy
9. continue until no pending authors remain

---

## Which authors to enrich

For the first implementation, the actor-enrichment job should work from **captured/hydrated post authors**, not from arbitrary external actor lists.

### Preferred source
Use author DIDs derived from the pipeline data already collected.

The cleanest options are:

1. **preferred**
   - derive unique author DIDs from the hydrated dataset or hydrated-state records

2. **acceptable fallback**
   - derive unique author DIDs from the captured post dataset if needed

The key requirement is:
- one enriched actor row per unique DID

---

## Dataset design

This phase creates a new dataset:

```text
data/
  actor_profiles/
    <actor_run_id>/
      actor_profiles_000001.jsonl.gz
      actor_profiles_000002.jsonl.gz