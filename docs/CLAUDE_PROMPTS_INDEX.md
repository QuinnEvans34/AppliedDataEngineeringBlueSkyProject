# CLAUDE_PROMPTS_INDEX.md
## Copy-Paste Prompts for the Three Refactors — Execution Order

This index points you at the three prompt files and tells you the
order to work through them. Each prompt file is broken into
**phases**. Each phase is a small, self-contained prompt you paste
into Claude in a fresh session. Review the output, commit, then move
on to the next phase. **Do not paste multiple phases at once.**

---

### Recommended Order

Do the streams in this order. Each stream can be paused at any
phase — the phases were designed to leave the repo in a working
state at each checkpoint.

1. **Profanity expansion** — smallest, safest, highest-value for
   demos. You can ship it without touching tasks.
   → `docs/CLAUDE_PROMPTS_PROFANITY.md` (4 phases)

2. **Enrichment task split** — medium blast radius; touches the
   live task chain. Do this after profanity is green so the
   split has the new UDF already in place.
   → `docs/CLAUDE_PROMPTS_ENRICHMENT.md` (3 phases)

3. **Docker containerization** — largest scope but mostly
   net-new files. Do last so the containers contain the finished
   SQL, not a mid-refactor state.
   → `docs/CLAUDE_PROMPTS_DOCKER.md` (4 phases)

---

### How to Use Each Phase Prompt

Each phase prompt block is wrapped in a fenced code block like this:

```
>>> PROMPT START >>>
...
<<< PROMPT END <<<
```

Copy the content **between** the markers (not the markers
themselves) into Claude. Claude will read the files referenced in
the prompt and implement the phase. When it finishes, it stops and
reports back so you can review the diff, run the validation, and
commit before moving on.

---

### One-Line Summary of Each Phase

**Profanity (4 phases)**
- A: Create config + whitelist tables. Seed with existing 37 terms.
- B: Add ~60 more terms and severity tiers.
- C: Rewrite the UDF template + build the deploy renderer script.
- D: Wire `severity_max` and `redaction_count` through
  `POSTS_ENRICHED` → `ML_READY`.

**Enrichment (3 phases)**
- A: Create the four staging tables in `ENHANCED`.
- B: Build the four per-concern staging-populating tasks.
- C: Add the assembler task + retire the old monolithic task.

**Docker (4 phases)**
- A: Base image + dev container + `.dockerignore` + `env.example`.
- B: `firehose` and `hydrate` service images + compose with
  default profile.
- C: Batch services (`twitter-trends`, `trend-match`, `sql-runner`)
  + `scripts/run_sql.py` + Makefile.
- D: GitHub Actions CI + `DOCKER_RUNBOOK.md`.

---

### Background the Prompts Assume Claude Will Read

Every phase prompt instructs Claude to read these files before
editing anything:

- `docs/SQL_FOLDER_OUTLINE.md` — the map of `sql/`
- `docs/PROMPT_PROFANITY_EXPANSION.md` — full spec behind the
  profanity work
- `docs/PROMPT_ENRICHMENT_TASK_SPLIT.md` — full spec behind the
  enrichment split
- `docs/PROMPT_DOCKER_PRODUCTION.md` — full spec behind the
  Docker work
- `docs/SNOWFLAKE_PROFANITY_UDF.md` — original UDF spec

The phase prompts themselves are deliberately short. The design
and rationale lives in the `PROMPT_*.md` spec docs. Claude reads
both.

---

### Checkpoints Between Phases

After each phase, before moving to the next, confirm:

- [ ] `git diff` looks right (no unrelated edits).
- [ ] The acceptance queries in the phase's "verify" section
      return what's expected.
- [ ] The repo still runs end-to-end in whatever mode you
      normally run it (host `.venv` today; Docker later).
- [ ] The change is committed with a clear message.
