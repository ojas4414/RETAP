---
name: okf-format
description: >-
  The OKF v0.1 document format — frontmatter schema, body conventions,
  cross-link syntax, and the knowledge/ directory layout. Reach for this
  whenever writing, amending, or checking any file under knowledge/; when
  deciding what fields an OKF document carries; when writing or resolving a
  cross-link between concepts; or when shaping extracted facts toward the
  structure they will eventually be stored in. Publish uses it on every
  document it writes; Extract references it so facts arrive in the right shape.
---

# OKF v0.1 — format specification

The published form of a fact. One concept per document.

## Directory layout

```
knowledge/
├── concepts/
│   └── <concept-name>.md      # one document per concept. Filenames are
│                              # authoritative — the concept vocabulary IS the
│                              # set of filenames here.
└── index.md                   # derived, regenerable listing of all concepts
```

Run logs are **not** under `knowledge/`. They are operational records, not
knowledge, and live in `logs/` — written by the orchestrator, format specified in
`orchestrator.md`.

`concepts/<concept-name>.md` filenames are lowercase kebab-case and match the
`concept` field inside the document exactly.

**`index.md` is derived, never authoritative.** It is regenerated from the
filenames in `concepts/`, so it cannot drift out of sync with reality. This is
also the file Extract's `concept_index` input is built from.

## Frontmatter schema

```yaml
---
fact_id: <string>            # minted by the staging layer on first write
concept: <string>            # kebab-case; matches the filename
value: <string>              # the current claim, in the source's terms
confirmed_by: <int>          # how many sources confirm it — see citation-rules
trust_score: <int>           # 0-100; see trust-scoring
last_confirmed: <timestamp>  # ISO-8601 UTC; last confirmation of this value
sources:                     # every source ever seen for this fact
  - url: <string>
    retrieved: <date>
    trust_score: <int>       # this source's score at retrieval time
    official: <bool>
previous_values: []          # amend history; see conflict-resolution
conflict: false              # true only on a flagged_conflict entry
---
```

`previous_values` and the `flagged_conflict` shape are specified in the
`conflict-resolution` skill, not here. Citation entry rules are in
`citation-rules`.

**Never drop `previous_values`.** Supersession amends; it does not overwrite.

`last_confirmed` and every `retrieved` are **full ISO-8601 UTC timestamps**
(`2026-09-06T16:07:41Z`), never bare dates — see Timestamps below.

## Multi-fact documents

A concept often carries more than one fact. When it does, the document uses the
`facts:` list shape: **document-level frontmatter holds only what the facts
share; everything a fact owns lives on the fact.**

```yaml
---
concept: bulk-operations          # shared
last_confirmed: <timestamp>       # shared: most recent confirmation of ANY fact
cross_links: [<concept>, ...]     # shared
facts:
  - fact_id: <string>
    value: <string>
    confirmed_by: <int>
    trust_score: <int, 0-100>
    last_confirmed: <timestamp>   # this fact's own, may predate the doc's
    sources: [ ... ]
    previous_values: []
    conflict: false
---
```

Nothing a fact owns may be hoisted to the document. Two facts under one concept
routinely have different sources, different trust scores, different confirmation
counts and different histories — a document-level `trust_score` would have to
pick one and would be a lie about the others.

The document-level `last_confirmed` is the **maximum** of the facts' own values:
"when did anything here last get confirmed". It is a convenience for scanning,
never a substitute for the per-fact value.

### Single-fact documents, and the transition

A document with exactly one fact uses the flat shape shown above — no `facts:`
wrapper, fields at the top level. It reads better and most documents are this.

When a second fact arrives for that concept, Publish **rewrites the frontmatter
into the `facts:` shape**, moving the existing fields into the first entry. This
is safe precisely because `fact_id` is content-derived (see `merge.md`): the
original fact keeps its identity across the reshape rather than being reminted.
The rewrite changes structure, never values.

## Timestamps

Every timestamp in an OKF document and in the source registry is **full ISO-8601
UTC, second precision**:

```
2026-09-06T16:07:41Z        # from: date -u +%Y-%m-%dT%H:%M:%SZ
```

Applies to `last_confirmed` (document level and per fact), `superseded_on`,
`flagged_on`, and the registry's `last_checked` and `fetch_method_last_probed`.

**A bare `2026-09-06` is invalid**, and the schema-validation hook rejects it.
The reason is not tidiness: two runs on the same day must be orderable. A
date-only `last_confirmed` cannot say which of this morning's and this evening's
runs confirmed a value, which makes it useless for exactly the question it
exists to answer.

The exception is a source's own `published` date, which is whatever the source
states — often a date, often absent. That one is copied, never generated, and
`null` when the source gives none.

## Body conventions

- Open with the current claim in plain prose. A reader should get the fact from
  the first sentence without parsing frontmatter.
- State the claim in the source's terms. The body is not the place to hedge,
  editorialize, or summarize the source's tone.
- On supersession, add a short "previously X, updated in [year]" note below the
  current claim — the frontmatter carries the full history, the body carries the
  human-readable version of it.
- On `flagged_conflict`, a clearly-marked section stating both values, both
  sources, and both trust scores side by side, written for a human adjudicator.
- Body prose is regenerated **only** when the value changes. A corroboration
  updates frontmatter and leaves the body untouched — see `publish.md`.

## Cross-links

Two forms, differing by one character:

| Form | Meaning |
|---|---|
| `[[concept-name]]` | **Resolved.** `knowledge/concepts/concept-name.md` exists. |
| `[[?concept-name]]` | **Pending.** The target concept has no document yet. |

Write the pending form whenever the target does not exist at the moment of
writing. Never emit a resolved link to a file that isn't there.

### End-of-run link re-scan

Documents are published in whatever order facts flow through the pipeline, so a
link written as pending early in a run may have its target published later in the
same run. A single pass at the end of the run fixes those up.

**Placement:** the last step of the run, as a final Publish invocation in
link-resolution mode, driven by the orchestrator after every fact has been
processed. Publish already holds `Read`/`Write` on `knowledge/`; no new tool and
no new script are needed.

**The pass — pure code, no judgment:**

1. Scan every document in `knowledge/concepts/` for `[[?...]]` references.
2. For each, check whether `concepts/<target>.md` now exists.
3. Exists -> rewrite in place, dropping the `?`. That is the entire operation:
   a one-character deletion.
4. Still missing -> leave it as `[[?...]]`. Next run's re-scan will catch it.

Find-unresolved, check-existence, rewrite-if-found. Three deterministic steps.
No LLM call belongs anywhere in this pass, and a pending link is never an error —
it is a correct record of a concept the knowledge base does not have yet.

## Index file

`index.md` lists every concept with a one-line description:

```markdown
# Concept index

- [[concept-name]] — one-line description of what this concept covers.
```

Regenerated from `concepts/` filenames. If it disagrees with the directory, the
directory is right.
