-- Profanity redaction UDF — TEMPLATE FILE.
-- Do not run this file directly in Snowflake. It contains two Jinja-style
-- placeholder tokens (see the UDF body below, labeled TERMS and WHITELIST)
-- that must be substituted by scripts/render_profanity_udf.py before
-- deployment. The renderer writes the runnable output to
-- sql/00_setup/_generated/03_udfs.rendered.sql.
--
-- Render then deploy:
--     python scripts/render_profanity_udf.py --terms-json <path>
--     (run the generated file in Snowflake)
--
-- The renderer strips the BEGIN / END guard block below before
-- substituting placeholders. Running THIS file directly emits the guard
-- VARIANT row whose payload tells the operator what to do instead.

-- ---- BEGIN TEMPLATE GUARD ----
SELECT TO_VARIANT(PARSE_JSON('{"error": "template not rendered — run scripts/render_profanity_udf.py --from-snowflake"}'));
-- ---- END TEMPLATE GUARD ----

USE DATABASE BLUESKYDATAENGINEERINGPROJECT;
USE SCHEMA ENHANCED;

CREATE OR REPLACE FUNCTION BLUESKYDATAENGINEERINGPROJECT.ENHANCED.CLEAN_PROFANITY(post_text STRING)
RETURNS OBJECT
LANGUAGE JAVASCRIPT
AS $$
    // Snowflake binds the argument as POST_TEXT (uppercase) inside JS UDFs.
    if (POST_TEXT === null || POST_TEXT === undefined) {
        return { post_text_clean: null, was_profanity_redacted: false,
                 redaction_count: 0, severity_max: null };
    }
    if (POST_TEXT === "") {
        return { post_text_clean: "", was_profanity_redacted: false,
                 redaction_count: 0, severity_max: null };
    }

    // Term list and whitelist are baked in at deploy time by
    // scripts/render_profanity_udf.py.
    const TERMS     = {{PROFANITY_TERMS_JSON}};
    const WHITELIST = {{PROFANITY_WHITELIST_JSON}};

    const SEVERITY_RANK = { mild: 1, strong: 2, sexual: 3, slur: 4 };
    const SEVERITY_NAME = { 1: "mild", 2: "strong", 3: "sexual", 4: "slur" };
    const LEET = { "0":"o", "1":"i", "3":"e", "4":"a", "5":"s", "7":"t",
                   "@":"a", "$":"s" };

    // Sentinels are alphanumeric-only strings so the separator-tolerance
    // character class [^A-Za-z0-9]? in match patterns cannot slip characters
    // into them. "qqz" prefix + zero-padded index makes collisions with real
    // English extremely unlikely.
    function sentinel(tag, idx) {
        return "qqz" + tag + String(idx).padStart(4, "0") + "zqq";
    }
    function escapeRegex(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // Step 1a — mask whitelist on the ORIGINAL text so whitelisted
    // words cannot match any profanity term.
    let masked = POST_TEXT;
    const whitelistStore = [];
    for (let i = 0; i < WHITELIST.length; i++) {
        const w = WHITELIST[i];
        const re = new RegExp("\\b" + escapeRegex(w) + "\\b", "gi");
        masked = masked.replace(re, function(match) {
            const ph = sentinel("WL", whitelistStore.length);
            whitelistStore.push({ ph: ph, original: match });
            return ph;
        });
    }

    // Step 1b — mask URLs so words inside URLs are not redacted.
    const urlStore = [];
    const URL_PATTERN = /https?:\/\/\S+|www\.\S+/gi;
    masked = masked.replace(URL_PATTERN, function(url) {
        const ph = sentinel("URL", urlStore.length);
        urlStore.push({ ph: ph, original: url });
        return ph;
    });

    // Step 2 — build a detection copy aligned to `masked` via a
    // collapse-with-map pass, followed by leetspeak normalization and
    // lowercasing. indexMap[i] = [maskedStart, maskedEndInclusive] for the
    // character at detection[i]. Leetspeak is 1:1, so applying it after
    // the collapse does not shift indexMap.
    const collapsedChars = [];
    const indexMap = [];
    {
        let i = 0;
        while (i < masked.length) {
            const ch = masked[i];
            const runStart = i;
            while (i + 1 < masked.length && masked[i + 1] === ch) { i++; }
            const runEnd = i; // inclusive
            const runLen = runEnd - runStart + 1;
            if (runLen >= 3) {
                collapsedChars.push(ch);
                indexMap.push([runStart, runStart]);
                collapsedChars.push(ch);
                indexMap.push([runStart + 1, runEnd]);
            } else {
                for (let k = 0; k < runLen; k++) {
                    collapsedChars.push(ch);
                    indexMap.push([runStart + k, runStart + k]);
                }
            }
            i++;
        }
    }
    const detection = collapsedChars
        .map(function(c) { return LEET[c] !== undefined ? LEET[c] : c; })
        .join("")
        .toLowerCase();

    // Step 3 — scan each term against the detection copy. Collect matches
    // as spans in the ORIGINAL masked string (via indexMap).
    const spans = [];
    let maxRankSeen = 0;
    for (let t = 0; t < TERMS.length; t++) {
        const entry = TERMS[t];
        const term = String(entry.term || "").toLowerCase();
        if (term.length === 0) continue;
        const sev = String(entry.severity || "").toLowerCase();
        const rank = SEVERITY_RANK[sev] || 0;
        const allowSep = !!entry.allow_separators;

        // Per-letter pattern: each letter is matched one-or-more times
        // (so the 3+ repetition collapse in the detection copy — which
        // leaves up to 2 copies of a run — still matches a single term
        // letter). When allow_separators is TRUE each letter position
        // also accepts a literal "*" as a censor-substitute (so "f*ck"
        // matches "fuck"), and we tolerate one non-alphanumeric between
        // each letter (so "f.u.c.k" matches "fuck").
        const parts = [];
        for (let j = 0; j < term.length; j++) {
            const ch = escapeRegex(term[j]);
            parts.push(allowSep ? "(?:" + ch + "|\\*)+" : ch + "+");
        }
        const body = allowSep ? parts.join("[^A-Za-z0-9]?") : parts.join("");
        // Word-boundary via explicit non-alphanumeric surround + lookahead.
        // The leading boundary is a non-capturing group we must skip past
        // in the match offset.
        const pattern = new RegExp(
            "(?:^|[^A-Za-z0-9])(" + body + ")(?=$|[^A-Za-z0-9])",
            "g"
        );
        let m;
        while ((m = pattern.exec(detection)) !== null) {
            const captureStart = m.index + (m[0].length - m[1].length);
            const captureEnd   = captureStart + m[1].length; // exclusive
            if (captureEnd <= captureStart) {
                pattern.lastIndex = m.index + 1;
                continue;
            }
            const mStart = indexMap[captureStart][0];
            const mEnd   = indexMap[captureEnd - 1][1] + 1; // exclusive
            spans.push({ start: mStart, end: mEnd, rank: rank });
            if (rank > maxRankSeen) maxRankSeen = rank;
            // Prevent zero-width loop.
            if (pattern.lastIndex === m.index) pattern.lastIndex++;
        }
    }

    // Step 4 — sort and merge overlapping spans. We keep `spans.length` as
    // the redaction_count (each detected match is a "span applied") but
    // merge overlapping ranges into a single [Profanity] token in output
    // so the text does not contain [Profanity][Profanity] for a single
    // overlapping hit.
    const redactionCount = spans.length;
    spans.sort(function(a, b) {
        if (a.start !== b.start) return a.start - b.start;
        return b.end - a.end;
    });
    const merged = [];
    for (let i = 0; i < spans.length; i++) {
        const s = spans[i];
        if (merged.length === 0) { merged.push({ start: s.start, end: s.end }); continue; }
        const last = merged[merged.length - 1];
        if (s.start < last.end) {
            if (s.end > last.end) last.end = s.end;
        } else {
            merged.push({ start: s.start, end: s.end });
        }
    }

    // Step 5 — build the output by replacing each merged range on `masked`
    // with [Profanity], then restore whitelist and URL sentinels.
    let cleaned;
    if (merged.length === 0) {
        cleaned = masked;
    } else {
        const out = [];
        let cursor = 0;
        for (let i = 0; i < merged.length; i++) {
            const r = merged[i];
            if (r.start > cursor) out.push(masked.substring(cursor, r.start));
            out.push("[Profanity]");
            cursor = r.end;
        }
        if (cursor < masked.length) out.push(masked.substring(cursor));
        cleaned = out.join("");
    }

    // Restore URL sentinels FIRST (they were masked second, so they
    // unmask first LIFO), then whitelist sentinels — this matters when
    // whitelist terms appear inside a URL (e.g. ".../classic-assets"):
    // the whitelist sentinels live inside the stored URL and must be
    // resurfaced before the whitelist-restore loop replaces them.
    for (let i = 0; i < urlStore.length; i++) {
        const e = urlStore[i];
        cleaned = cleaned.split(e.ph).join(e.original);
    }
    for (let i = 0; i < whitelistStore.length; i++) {
        const e = whitelistStore[i];
        cleaned = cleaned.split(e.ph).join(e.original);
    }

    return {
        post_text_clean: cleaned,
        was_profanity_redacted: redactionCount > 0,
        redaction_count: redactionCount,
        severity_max: redactionCount === 0 ? null : (SEVERITY_NAME[maxRankSeen] || null)
    };
$$;

-- Reminder: suspend warehouse after running validation queries.
-- ALTER WAREHOUSE COMPUTE_WH SUSPEND;
