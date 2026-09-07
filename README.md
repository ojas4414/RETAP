# amazon-ads-kb

A dynamic knowledge acquisition system for Amazon Advertising, built as a Claude
Code project. It discovers source material, extracts atomic facts, validates them
against what already exists, merges duplicates, and publishes the result as OKF
(Open Knowledge Format) documents.

It is designed to be safe to re-run: unchanged content is skipped and Merge
suppresses exact duplicates.

```
Discover  ->  Extract  ->  Validate  ->  Merge  ->  Publish
```

...supervised by an **orchestrator** that owns sequencing, failure handling and
the run log.

## Setup

Requires Node.js 18+, Python 3.10+, and Claude Code.

```bash
git clone https://github.com/ojas4414/RETAP.git amazon-ads-kb
cd amazon-ads-kb

pip install 'markitdown[pdf]'      # PDF/docx normalization
npx playwright install             # browser binaries for JS-rendered pages
export TAVILY_API_KEY=...          # search MCP key, read from the environment
```

MCP servers are declared in `.mcp.json` and need no custom code — Claude Code is
the MCP client. Playwright and Tavily are pre-built servers, registered the way a
library is installed.

On first launch Claude Code will ask you to trust the workspace. Accept it, or
the `permissions` block in `.claude/settings.json` is ignored and every script
call is refused.

## Run it

```bash
claude -p "ingest https://advertising.amazon.com/API/docs/en-us/, update the bundle"
claude -p "update the bundle"      # re-check every source in the registry
```

Any ingest/update request invokes the `orchestrator` agent, which drives the five
stages in sequence. A URL that is not yet in `knowledge/.sources.json` is added to
the registry first.

Run the tests with:

```bash
python -m pytest tests/ -q
```

### What to expect on a fresh clone

**`update the bundle` on a fresh clone will report every source unchanged and
write nothing.** That is not a failure — it is the re-run guarantee. The registry
committed with this repo already holds a content hash for each source, so Discover
compares, finds no change, and correctly declines to re-fetch or re-process. The
run log records the skip.

To watch it actually acquire knowledge, do one of these:

```bash
# 1. Ingest a source it has never seen. This is the honest demo.
claude -p "ingest https://advertising.amazon.com/API/docs/en-us/reference/api-overview, update the bundle"

# 2. Or force an existing source to be treated as uncaptured, then run.
python scripts/hash_compare.py reset amazon-ads-api-docs
claude -p "update the bundle"
```

Option 2 clears that source's stored hash, so the next run reports `changed`,
re-fetches, and republishes its concepts.

**Three things will silently stop it if they are missing:**

| If | Then |
|---|---|
| The workspace is not trusted | Claude Code ignores the whole `permissions` block and every `python scripts/...` call is refused. Accept the trust prompt on first launch. |
| `npx playwright install` was not run | The JS-rendered source cannot be fetched. The two static sources still work. |
| `TAVILY_API_KEY` is unset | The search MCP fails to start. Nothing in the pipeline depends on it today, so the run still completes. |

A full run takes roughly 20-40 minutes, most of it waiting on model calls and one
browser render. Progress is visible in `logs/run_<timestamp>.jsonl` as it goes.

On Windows or a restricted environment where the default system temp directory
is unavailable, use:

```powershell
python -m pytest tests/ -q -p no:cacheprovider --basetemp .pytest-tmp
```

## Recovering an Interrupted Run

If a run halted after Discover captured a source but before Publish completed,
explicitly reset that source's hash before retrying it. This preserves its URL
and fetch-method memoization while making the next run process its content again:

```powershell
python scripts/hash_compare.py reset amazon-ads-api-docs
claude -p "update the bundle"
```

## The one real decision

**Deterministic operations live in `scripts/`. Fuzzy judgment lives in agent
prompts.**

Fetching, hashing, diffing against the last run, stripping HTML, comparing
strings, looking up a domain's trust baseline — these have one correct answer, so
they are code, and they are testable in isolation. Deciding whether a paragraph
holds one fact or three, whether two differently-worded statements mean the same
thing, whether a source deserves belief — these have no closed form, so they are
prompts.

The line is drawn *inside* most stages, not just between them. Validate is the
clearest case: an exact-match duplicate is caught by a string comparison with no
model call at all, its trust baseline comes from a lookup in
`scripts/trust_lookup.py`, and only what survives both reaches judgment — which
then adjusts the baseline by at most ±10 rather than reasoning it from scratch.

## Layout

| Path | Purpose |
|---|---|
| `CLAUDE.md` | Scope, behaviour, the entry point, and the principle above |
| `.claude/agents/` | Orchestrator + one prompt per pipeline stage |
| `.claude/skills/` | OKF format, citations, dedup, trust scoring, conflict resolution |
| `.claude/hooks/` | Four PreToolUse hooks — the enforcement layer |
| `.claude/settings.json` | Hook registration and permissions |
| `scripts/` | Deterministic helpers. No model calls |
| `staging/` | Merge's working area, one file per concept |
| `knowledge/` | The OKF bundle. Only Publish writes here |
| `knowledge/.sources.json` | Source registry: per-source hash, last check, failure count |
| `logs/` | Run logs, JSON Lines, one file per run |
| `tests/` | Tests for `scripts/` and the hooks |

## How re-run safety works

Skip-if-unchanged is enforced in two places and nowhere else:

- **Discover** hashes the *cleaned* content and compares it to the last run's
  hash. Unchanged means nothing downstream runs.
- **Merge** refuses to write on a `duplicate_exact` verdict, so an unchanged fact
  never reaches Publish.

This is why `scripts/clean_content.py` must be byte-stable: its output feeds the
hash, and any instability there would turn every run into a false "changed".
Verified in practice — three separate browser renders of the same JS-rendered
page across five hours produced an identical SHA-256.

Discover also memoizes *how* to fetch each source. A page that fails the
usable-content check is marked `js_rendered` and thereafter goes straight to
Playwright, re-probed with a plain fetch only every 30 days.

## Enforcement

Agent prompts describe intent; hooks enforce it. An instruction in a prompt is
not a constraint.

| Hook | Enforces |
|---|---|
| `schema_validation.py` | Every stage handoff carries a valid payload for its target |
| `validate_before_write.py` | Only Publish writes to `knowledge/`, and only behind a real Merge verdict |
| `orchestrator_write_scope.py` | The orchestrator writes `logs/` and runs only a clock |
| `task_scope.py` | Validate may escalate only to Discover |

All four fail **closed** on a rule violation and **open** on their own internal
error: a broken hook must never wedge the pipeline.

## Documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system and agent architecture,
  component responsibilities, data flow, where the code/judgment line falls.
- [`docs/DESIGN.md`](docs/DESIGN.md) — tradeoffs and why, what I would improve,
  how Claude Code was used.

## Known limitations

- **`STAGE_TIMEOUT_SECONDS` is advisory.** A `Task` call blocks until the
  subagent returns, so the orchestrator cannot preempt a hung stage. The value is
  useful for reasoning about a run afterwards, not as a guarantee.
- **Cross-concept relatedness is not modelled.** Cross-links are written when a
  document mentions another concept; nothing infers relatedness beyond that.
- **The trusted-domain list is short by design.** Unlisted domains score low
  *pending review* and are flagged, never silently accepted or rejected.
- **The usable-content check is length-based.** A page that comes back
  non-trivially long passes it, so GitHub's 2.7KB "Uh oh! There was an error
  while loading" shell was accepted as content and yielded zero facts. Detecting
  *worthless* content, as opposed to *absent* content, needs more than a length
  threshold.
- **Contradictions escalate to a human.** After one automatic re-verification, an
  unresolved disagreement is written as a `flagged_conflict` with both values and
  both sources. The system never picks a winner.
