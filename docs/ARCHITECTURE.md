# System & Agent Architecture

## The shape of the problem

Keeping a knowledge base current is not one problem. It is five, and they fail in
different ways:

1. Something out there changed — but what, and how do we know without re-reading
   the world every run?
2. This page says things — but which of them are *facts*, and where does one fact
   end and the next begin?
3. This fact resembles one we hold — is it the same, newer, or contradictory?
4. Given that answer, what should actually change on disk?
5. How is that change expressed in a format a person and a machine can both read?

Each has a different failure mode and a different correctness criterion, so each
is a separate agent with a separate toolbox. Discover cannot interpret content.
Validate cannot write. Publish cannot fetch. The boundaries are not decoration —
they are what makes each stage testable and each failure attributable.

```
                    ┌──────────────┐
                    │ orchestrator │  sequencing, retry/skip/halt, run log
                    └──────┬───────┘
       ┌──────────┬────────┼────────┬──────────┐
       ▼          ▼        ▼        ▼          ▼
   Discover → Extract → Validate → Merge → Publish
   what        what      how does   what      how is
   changed?    does it   it relate  changes?  it written?
               say?      to ours?
```

## The one decision everything else follows from

**Deterministic operations are code. Fuzzy judgment is prompts.**

The brief asks for this line to be drawn and explained. The important part of our
answer is that the line runs *inside* most stages, not merely between them.

Validate is the clearest case. A candidate fact arrives and three things happen in
order:

| Step | Kind | Where |
|---|---|---|
| Normalize and compare against stored facts of the same concept | code | string compare, no model call |
| Look up the source domain's trust baseline | code | `scripts/trust_lookup.py` |
| Decide what a *mismatch means* — contradiction, supersession, or different scope | judgment | the prompt |

An exact duplicate is settled by a string comparison and never reaches a model.
A trust score is never reasoned from scratch; the list produces a baseline and
judgment adjusts it by at most ±10, a bound tight enough that no adjustment can
move a source across a band boundary. Judgment is spent only where there is no
closed form.

Worth stating plainly: **the duplicate path has not been exercised on real
data.** Every verdict every run has produced is `new` — no duplicates, no
contradictions, no supersessions. That is partly by construction: when a page is
re-fetched unchanged, Discover skips it before Extract ever runs, so the cheap
comparison downstream rarely gets the chance to fire. The dedup pre-filter and
the two gates on `confirmed_by` are implemented and unit-tested, not
battle-tested.

The same split appears in Discover (fetch, clean, hash, diff — all code; the only
judgment is none), in Extract (cleaning is code, fact boundaries are judgment), in
Merge (the corroboration trust floor is arithmetic, amend mechanics are judgment)
and in Publish (frontmatter is templated, prose is written).

## Stage responsibilities

**Orchestrator** — supervises; not a pipeline stage. Drives the sequence via
`Task`, owns retry / skip-and-log / halt, the one-shot contradiction retry, and
the run log. It has `Task`, `Write` restricted to `logs/`, and `Bash` restricted
to reading a clock. It deliberately has no `Read`: everything else is delegated.

**Discover** — owns *all* network access in the system. Fetch, clean, hash,
compare against the last run, report `changed`/`unchanged`/`failed`. It never
interprets content and never decides what is important. It memoizes *how* to
fetch each source, so a JS-rendered page is not re-probed with a plain fetch every
run — only every 30 days.

**Extract** — the first stage where judgment does the work. Turns cleaned markdown
into atomic facts, each tagged to a concept, each carrying its source. It performs
a cheap string lookup against the existing concept index to reuse names, and
deliberately does *not* attempt semantic matching — that is Validate's job, and
duplicating it here would pay twice for one answer.

**Validate** — classifies into exactly one of five verdicts (`new`,
`duplicate_exact`, `duplicate_corroborating`, `contradiction`, `supersession`).
It never writes and never discards; even a trivial exact duplicate is handed to
Merge. That is deliberate: Merge can then be tested on "produces no write" the
same way it is tested on every other verdict.

**Merge** — the only stage permitted to decide *not* to write. Acts on the verdict
against a staging layer, mints `fact_id` via `scripts/mint_fact_id.py`, and hands
Publish a verdict plus changed fields — never finished markdown. The ID is derived
from the fact's own content, so parallel Merge instances need no shared counter
and the same fact re-extracted later keeps its identity.

**Publish** — the OKF specialist. Templated frontmatter, written prose, and prose
only where the value actually changed. A corroboration updates counts and
citations and leaves the body untouched, because regenerating it would let wording
drift on a re-run where nothing substantive happened.

## Data flow, and two kinds of cross-agent call

Stages hand each other structured payloads, never prose. Because a `Task` payload
is a prompt string rather than a typed struct, structured data travels inside
`<PAYLOAD>…</PAYLOAD>` markers so a hook can find and validate it.

Two different mechanisms exist and are deliberately not merged:

- **Peer escalation.** Validate → Discover, mid-classification, to re-verify a
  possibly-stale source before reaching a verdict. Narrow, single-fact, bypasses
  the orchestrator entirely — no run-level decision is being made.
- **Orchestrator retry.** After Validate returns a *final* `contradiction`, the
  orchestrator triggers exactly one re-verification pass. This reopens a completed
  decision and affects run-level flow, so it belongs to the supervisor.

While a fact is in that retry, only facts sharing its `concept` pause; unrelated
concepts keep flowing.

## Enforcement: hooks, not prose

An instruction in an agent file is a wish. Four `PreToolUse` hooks make the
important ones real:

| Hook | Enforces |
|---|---|
| `schema_validation.py` | Handoffs carry a valid payload for the target stage |
| `validate_before_write.py` | Only Publish writes `knowledge/`, behind a real Merge verdict |
| `orchestrator_write_scope.py` | Orchestrator writes only `logs/`, runs only a clock |
| `task_scope.py` | Validate may escalate only to Discover |

Per-agent scoping is possible because `agent_type` appears in the hook payload —
verified empirically against Claude Code 2.1.261 rather than assumed. All four
fail **closed** on a violation and **open** on their own internal error: a broken
hook must never wedge the pipeline.

One of these has caught real defects in live runs; the rejections are in the
logs, verbatim:

- `missing required field(s): candidate, stored_facts` — the orchestrator had
  batched all facts into a single Validate call, violating Validate's own
  per-fact contract.
- `missing required field(s): concept_index` — a stage handoff omitting a field
  the target requires.
- `mode=<one of resume_check>` and `missing required field(s): status` — a
  resume check being validated as if it were a verdict, which is what led to
  mode calls getting their own schema.

The other three hooks are proven by tests rather than by firing in a live run.
Nothing has yet attempted a write outside its scope during an actual pass, which
is the outcome you want but is not the same as having been tested by events.

## Re-run safety

Enforced in exactly two places:

- **Discover** hashes the cleaned content and compares it to the stored hash.
- **Merge** refuses to write on `duplicate_exact`.

Nothing downstream needs its own change check. This is why `clean_content.py` must
be byte-stable: its output feeds the hash. Verified — three separate browser
renders of the same JS-rendered page, hours apart, produced an identical SHA-256,
and two back-to-back renders were byte-identical.

The registry (`knowledge/.sources.json`) keeps per-source state: last hash, last
check, memoized fetch method, and a consecutive-failure counter kept strictly
distinct from the JS-rendering signal — a page that needs a browser is a working
source needing a different tool, not a failure.

## Knowledge quality

Every published fact carries `sources`, `confirmed_by`, `trust_score` and
`last_confirmed`. Two rules keep those numbers honest:

- `confirmed_by` is **not** `len(sources)`. A corroborating source must pass two
  gates to increment it — **independent?** (judgment: is this a mirror or
  republish of something already cited?) then **trusted enough?** (arithmetic:
  within `CORROBORATION_TRUST_FLOOR` of the existing citations' average). A source
  failing either is still cited; it just doesn't count.
- Supersession **amends**. The old value moves into `previous_values` with its own
  source, date and score. Nothing is silently overwritten, which is what makes
  "when did the minimum bid change?" answerable later.

Where sources genuinely disagree and one re-verification fails to resolve it, the
system writes a `flagged_conflict` with both values and both sources and stops.
It never picks a winner.

**None of this paragraph has been exercised on live data.** Every registered
source is first-party Amazon documentation and they do not contradict each other,
so no supersession has ever amended a value and no `flagged_conflict` has ever
been written. The formats are specified in `conflict-resolution`, the verdicts
exist in Validate's schema, and the hook enforces their shape — but the only
evidence they behave correctly is tests, not runs. Proving them needs two sources
that genuinely disagree, which is the first thing I would add next.
