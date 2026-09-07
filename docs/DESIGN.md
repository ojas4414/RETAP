# Design Document

Tradeoffs, what I would improve, and how Claude Code was actually used.

## Tradeoffs, and why

### An orchestrator, rather than five peer agents

Five stages calling each other directly would be simpler to draw and worse to
operate. Failure handling has to live *somewhere*: when Discover can't reach a
source, someone must decide retry / skip / halt, and that decision is about the
run, not about the fact. Putting it in a supervisor keeps every stage's prompt
about its own job.

The cost is one extra hop per stage and a supervisor that can become a
bottleneck. The benefit showed up immediately in practice: when a stage's payload
was rejected by a hook, the orchestrator corrected and re-sent it, and the reason
appeared in the run log. No stage had to know about retries.

### Validate never writes and never discards

The tempting shortcut is to let Validate drop exact duplicates — it already knows.
We deliberately didn't. Every verdict, including `duplicate_exact`, goes to Merge.

This costs a message. It buys a single place where "should this be written?" is
decided, which means Merge can be tested on *produces no write* exactly as it is
tested on every other verdict, and it means a fact never disappears in a stage
that isn't supposed to be making that call.

### Deterministic `fact_id`s instead of a counter

An early implementation numbered facts per concept. Parallel Merge instances have
no shared counter, so one run produced `amazon-ads-api-001` alongside
`bulk-operations-0001`. The fix was not to coordinate but to remove the need:
`fact_id = <concept>-<first 8 hex of sha256("concept:value")>`.

A property fell out that nobody asked for: **IDs are re-run stable**. The same
fact extracted next month hashes to the same ID. A supersession therefore keeps
the document's original ID and records the old value in `previous_values`, rather
than minting a second identity for the same claim.

### Trust from a list, adjusted by judgment — never reasoned from scratch

Trust could plausibly be pure judgment. We made it a code lookup with a bounded
adjustment, for a reason we then watched play out: when Validate lacked access to
`trust_lookup.py`, every instance reasoned a plausible-looking baseline the list
had never approved, and one returned `0.9` on what is a 0–100 scale.

The ±10 bound is doing real work. With bands at 85–95 / 40–60 / 10–20, no
adjustment can move a source across a band. Judgment refines within a category; it
cannot overrule the list. If a source seems to deserve more movement than that,
the honest fix is the list, not the score.

### Hooks over prose

Every scoping rule in this system is stated twice: once in the agent file so a
reader understands it, once in a hook so it is true. The distinction mattered more
than expected — `tools:` in agent frontmatter can grant `Task` but cannot restrict
*which* agent it targets, so "Validate may only escalate to Discover" is
unenforceable as written and becomes real only in `task_scope.py`.

### Staging outside `knowledge/`

Merge writes to `staging/` at the project root, not `knowledge/.staged/`. Putting
it inside would have forced the write-gate hook to exempt the one agent it most
needs to constrain. Keeping it out means the rule stays absolute: *only Publish
writes under `knowledge/`* — no carve-outs.

### Model choice: sonnet everywhere, for now

The orchestrator and Validate were specified as opus, because failure
interpretation and contradiction-vs-supersession are the hardest judgment in the
system. In practice the registered sources produce a corpus where that judgment
never fires: a full run returned 13 verdicts, all `new` — zero duplicates, zero
contradictions, zero supersessions. Opus was being paid for reasoning the data
never asked for, at several times the cost and latency.

All six agents now run on sonnet. The honest caveat: for a corpus where sources
genuinely disagree, or where semantic dedup across differently-worded facts
matters, opus on Validate is the better choice and the `model:` field is a
one-line change. This is a cost decision made against observed verdict
distribution, not a claim that the stages are equally easy.

## What I would improve

**Concurrency was an afterthought.** The first full runs processed facts serially
because nothing said otherwise, and a run spent most of its wall-clock waiting on
calls that could have overlapped. Making per-fact parallelism explicit cut the
Validate phase from roughly twenty minutes of serial calls to about ninety
seconds: thirteen facts dispatched in one batch and returned together. (Discover
separately fell from 23 minutes to 4, but that was skip-if-unchanged declining to
re-fetch, not parallelism.) It should have been in the design from the start, not
discovered by watching a log.

**`STAGE_TIMEOUT_SECONDS` is unenforceable.** A `Task` call blocks until the
subagent returns; the orchestrator cannot poll or preempt it. The config value
survives as an advisory budget, clearly labelled. Genuinely fixing it needs an
out-of-band watchdog the current architecture has no place for. This cost a real
run: I killed a pipeline that was working fine because it *looked* hung.

**The run log was write-only until it wasn't.** The orchestrator holds `Write` but
not `Read`, so it cannot append. It buffered events and flushed late — meaning the
log was reliably absent exactly when a crash made it valuable. It now rewrites the
whole file after each event. A separate attempt to work around the missing `Read`
by opening sidecar files produced three logs for one run, which is worse than one
slow log.

**Publish does not verify it wrote everything it was handed.** A run staged 13
concepts and published 12, and nothing noticed: the index — written by Publish —
listed all 13, so `knowledge/index.md` pointed at a document that did not exist.
The index is specified as *derived from filenames*, which is exactly the property
that would have caught this, but it is generated from Publish's own idea of what
it wrote rather than from a directory listing. A count assertion between staging
and `concepts/` at end of run would close it.

**Trust adjustment is bounded in prose but not in code.** The same staged concept
carried `trust_score: 25` on a fact sourced from `advertising.amazon.com`, whose
list baseline is 92. The ±10 rule makes 82–100 the only valid range, and 25 is
not inside any band. The schema hook checks that a trust score is an integer in
0–100, which 25 satisfies — nothing checks it against the baseline the lookup
returned. That document was withheld from the bundle rather than published with a
score the system's own rules forbid. Enforcing the bound needs the hook to see
both the baseline and the final score, which means Validate must report both.

**Cross-concept relatedness is not modelled.** Cross-links are written when a
document explicitly mentions another concept, and an end-of-run pass resolves
`[[?pending]]` markers whose target has since been published. Nothing infers that
two concepts are related when neither names the other. That is a real gap, noted
rather than hidden: doing it properly needs an embedding or a curated ontology,
and neither fits a one-week scope.

**Extract depends on the cleaner more than it should.** On one source the cleaned
markdown concatenated changelog items without delimiters, and Extract inferred
boundaries from capitalization — judgment compensating for a code-side defect.
The hash is unaffected (the concatenation is deterministic, so re-run safety
holds), but the right fix is a block separator in `clean_content.py`.

**Only `scripts/` and the hooks are tested.** 52 tests cover the deterministic
half. The agents are prompts, and testing them would mean asserting on model
output; the honest alternative — golden-file tests over recorded fixtures — was
out of scope.

## How Claude Code was used

The division of labour was: **I designed, Claude Code implemented and then proved
me wrong.**

Every architectural decision here — the orchestrator, the five verdicts, Validate
never writing, the two gates on `confirmed_by`, staging outside `knowledge/` —
was specified before any file was written, and several were revised mid-build
because running the thing exposed a flaw.

Concretely, the loop that produced this repo:

1. **Specify, then scaffold.** Agent and skill files were written from an explicit
   design, one at a time, reviewed before moving to the next. Claude Code wrote
   syntax; the decisions came first.
2. **Verify claims instead of accepting them.** The Playwright MCP tool names in
   `discover.md` were not guessed — the server was launched and its `tools/list`
   read, returning 24 tools of which five were granted. `agent_type` in hook
   payloads was confirmed by running a real subagent write and dumping the
   payload, which also revealed that the key is *absent* for main-session calls
   rather than null.
3. **Let the system catch its own inconsistencies.** The schema hook rejected the
   end-of-run `resolve_links` call because a mode call is not a verdict; it
   rejected a batched Validate invocation that violated Validate's own per-fact
   contract. Both were design bugs, found by the enforcement layer rather than by
   reading.
4. **Check reported results against disk.** Sub-sessions reported what they had
   done; concept counts, registry fields and log contents were re-read
   independently before being believed. One report of "the run is resuming in the
   background" was false — the process had already exited.

The most useful thing this produced was a habit of distrusting confident output.
A sub-agent claimed a stalled run had never reached Discover; the registry showed
Discover had completed and updated three fields. Both the claim and my own earlier
inference ("38 browser processes, so Playwright is active" — they were the user's
Chrome windows) were wrong, and only looking at the actual state settled it.

## Honest status

Working and demonstrated on live data: the five-stage pipeline end to end,
producing the **12 OKF concept documents and index** now in `knowledge/`;
skip-if-unchanged
(a source with a matching hash is skipped without a fetch); the static ↔
JS-rendered fetch-method flip and its memoization; deterministic cleaning verified
by identical hashes across separate renders; and all four hooks blocking real
violations.

The bundle's content-derived `fact_id`s are reproducible: running
`scripts/mint_fact_id.py` on a published document's concept and value returns
that document's exact identifier.

An earlier run did halt at Merge because deterministic ID minting was specified
but unavailable in Merge's toolbox — an LLM was being asked to compute a SHA-256.
`scripts/mint_fact_id.py` and a scoped permission fixed it, and that is the
sharpest example in this project of the code-vs-judgment line being drawn in the
wrong place.

Not finished: the bundle in this repo is regenerated per run rather than
accumulated across many, so document count depends on the sources registered;
three source types are registered (JS-rendered SPA, static HTML, raw markdown) and
a PDF path exists in `clean_content.py` but no PDF source is registered; and
contradiction handling is implemented and specified but has not been exercised
against two genuinely disagreeing sources, because none of the registered sources
disagree yet.
