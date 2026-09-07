# amazon-ads-kb

A knowledge acquisition system for Amazon Advertising. It discovers source material,
extracts atomic facts from it, validates them, merges them into the existing corpus,
and publishes the result as OKF (Open Knowledge Format) documents under `knowledge/`.

## Scope

In scope:
- Amazon Ads product surfaces (Sponsored Products/Brands/Display, DSP, AMC, Ads API).
- Official documentation, API references, changelogs, and help-center articles.
- Facts that are durable and citable: definitions, constraints, limits, eligibility
  rules, metric semantics, API contracts.

Out of scope:
- Speculation, forecasts, and third-party opinion presented as fact.
- Account-specific or campaign-specific data.
- Anything that cannot be traced to a retrievable source URL.

## Pipeline

```
discover  ->  extract  ->  validate  ->  merge  ->  publish
  (what changed?) (what does it say?) (is it sound?) (does it fit?) (write it)
```

Each stage is a subagent in `.claude/agents/`. Stages hand off structured data, not prose.
No stage reaches backwards; if a stage needs something upstream, it fails loudly instead
of re-deriving it.

## Running it

```
claude -p "ingest https://advertising.amazon.com/API/docs/en-us/, update the bundle"
claude -p "update the bundle"          # re-check every known source
```

If a prior run halted after Discover captured content but before Publish
completed, reset each interrupted source before retrying so it is not skipped as
unchanged:

```
python scripts/hash_compare.py reset <source_id>
claude -p "update the bundle"
```

**Any request to ingest a URL, update/refresh the bundle, check sources for
changes, or acquire knowledge means: invoke the `orchestrator` agent via `Task`.**
Do not perform the pipeline inline, and do not invoke the five stages directly —
the orchestrator owns sequencing, failure handling, the contradiction retry and
the run log, and a stage run outside it has none of that.

If the request names a URL that is not yet in `knowledge/.sources.json`, add it
to the registry first — `url`, `official`, `fetch_method: static`, everything
else null or zero — then hand the orchestrator that `source_id`. A source with a
null `content_hash` is reported as changed on its first run, which is correct: it
has never been captured.

With no URL named, the run covers every source in the registry.

This is the only entry point. Everything below describes how the system behaves
once it is running.

## Core principle: code vs. judgment

The single most important rule in this repo.

**Deterministic operations live in `scripts/`.** Fetching a URL, hashing content,
diffing against the last run, stripping HTML and nav chrome, comparing strings,
computing IDs. These have one correct answer. They must never be done by an LLM
"reading carefully" — an LLM eyeballing two hashes is a bug, not a feature.

**Fuzzy judgment lives in agent prompts (`.claude/agents/`).** Deciding whether a
paragraph contains one fact or three, whether two differently-worded statements mean
the same thing, which concept a fact belongs to, whether a source actually supports
a claim. These have no closed form. They must never be faked with a regex.

When adding a capability, ask which side of that line it sits on **before** writing it.
If it is genuinely both, split it: a script that produces candidates, an agent that
judges them.

## Layout

| Path | Purpose |
|---|---|
| `.claude/agents/` | The orchestrator plus one prompt per pipeline stage. |
| `.claude/skills/` | Shared rulebooks (OKF format, dedup, citations, trust, conflicts). Loaded on demand. |
| `.claude/settings.json` | Hook registration. |
| `.claude/hooks/` | Four PreToolUse hooks. The enforcement layer for rules prose cannot enforce. |
| `.mcp.json` | Playwright MCP (JS-rendered pages) + Tavily search MCP. |
| `scripts/` | Deterministic helpers. Pure, testable, no LLM calls. |
| `staging/` | Merge's working area, one file per concept. Outside `knowledge/` on purpose. |
| `knowledge/` | Published OKF documents. Write-gated — only Publish writes here. |
| `knowledge/.sources.json` | The source registry. Operational, not knowledge — exempt from the write gate. |
| `logs/` | Run logs, JSON Lines, one file per run. Written by the orchestrator, nowhere else. |

MCP servers are registered in `.mcp.json` and need no custom code — Claude Code is
the MCP client. The search server is **Tavily**, reading `TAVILY_API_KEY` from the
environment; no key is stored in the repo.

Playwright also needs its browser binaries (`npx playwright install`), which is a
separate step from registering the server.

## Conventions

- Every published fact carries at least one source citation. No citation, no publish.
- `knowledge/` is append-and-amend, never silently overwritten; merge decisions are
  explicit and recorded.
- Source URLs and their last-seen content hashes are tracked so `discover` can report
  deltas rather than re-processing the world every run.

The **source registry** lives at `knowledge/.sources.json`. Discover maintains it
every run; `scripts/hash_compare.py` owns every write to it. Per source: `url`,
`official`, `fetch_method`, `fetch_method_last_probed`, `content_hash`,
`last_checked`, `consecutive_failures`.

The **OKF naming scheme** is in the `okf-format` skill: one document per concept
at `knowledge/concepts/<concept-name>.md`, kebab-case, with `knowledge/index.md`
derived from those filenames rather than maintained alongside them.

## Orchestration

The pipeline is supervised by `orchestrator.md`, not run as five independent peer
agents. The orchestrator drives Discover -> Extract -> Validate -> Merge ->
Publish in sequence via `Task`, and owns run-level failure handling (retry, skip,
halt), the contradiction retry, and user notification.

Two kinds of cross-agent calls exist, and they are NOT the same mechanism:

- **Peer-to-peer escalation** (Validate -> Discover mid-classification, to
  re-verify a possibly-stale source before finishing its own verdict): narrow,
  single-fact, bypasses the orchestrator entirely.
- **Orchestrator-driven retry** (after Validate returns a FINAL `contradiction`
  verdict): reopens a completed decision and affects run-level flow — the
  orchestrator's call, not any individual stage's.

Config lives in exactly one place, `orchestrator.md`'s Config block, and travels
to stages as parameters on the `Task` payload. A stage never hardcodes a config
value or reads it from another file; a missing one is a malformed payload, not a
default to assume.

## Re-run safety

Skip-if-unchanged is enforced at **Discover** (hash comparison against the last
run) and at **Merge** (a `duplicate_exact` verdict never reaches Publish — no
write happens). Nothing downstream needs its own separate "did this change" check.

This is also why `clean_content.py` must be deterministic: its output feeds the
hash, so any instability there turns every run into a false "changed".

## Logging vs. notification

Different systems, different frequencies. Everything is logged; almost nothing
interrupts the user.

Only three things notify: a fatal halt, a `flagged_conflict` write confirmed by
Merge, and a source failing on three *consecutive* runs. Everything else — stage
results, `supersession`, `duplicate_corroborating`, resolved retries — is logged
silently to `logs/`. See `orchestrator.md` for the full split.

## Enforcement

Four PreToolUse hooks in `.claude/hooks/`. They exist because an instruction in
an agent file is not a constraint — a hook is:

| Hook | Enforces |
|---|---|
| `schema_validation.py` | Stage handoffs carry a valid `<PAYLOAD>` for the target stage. |
| `validate_before_write.py` | Only Publish writes to `knowledge/`, and only behind a real Merge verdict. |
| `orchestrator_write_scope.py` | The orchestrator writes to `logs/` and nowhere else. |
| `task_scope.py` | Validate may only escalate to Discover. |

All four fail **closed** on a rule violation and **open** on their own internal
error. A broken hook must never wedge the pipeline.
