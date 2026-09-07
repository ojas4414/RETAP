---
name: conflict-resolution
description: >-
  What to do when a new fact disagrees with a stored one — the amend format
  for supersession (the previous_values history array), the flagged_conflict
  entry format for unresolved disagreements, and the retry-once rule that
  decides between them. Reach for this when a candidate's value conflicts
  with what is stored, when writing or reading previous_values, when a
  contradiction survives re-verification, or when a human reviewer needs to
  adjudicate two sources. Merge writes these formats; Publish renders them.
---

# Conflict resolution

Two sources disagree. There are exactly two outcomes: one supersedes the other,
or neither wins and a human decides.

Nothing in this system silently picks a winner.

## Which outcome, and who decides

| Situation | Outcome |
|---|---|
| Newer source, older value was correct at its time | `supersession` — amend |
| Genuine disagreement, survives re-verification | `flagged_conflict` — flag for a human |

Validate classifies. The orchestrator drives the retry. Merge writes. Publish
renders. No stage does two of those jobs.

## The retry-once rule

1. Validate returns a **final** `contradiction` verdict.
2. The orchestrator triggers **exactly one** re-verification pass — `discover ->
   extract -> validate`, scoped to that single fact.
3. Second pass returns something other than `contradiction` -> proceed normally.
   The disagreement was stale data, and re-fetching resolved it.
4. Second pass still returns `contradiction` -> **stop**. Merge writes a
   `flagged_conflict` entry. No further auto-retry, ever.

One retry, not a loop. A disagreement that survives a fresh fetch is a real
disagreement between sources, and re-fetching a third time will not change that —
it will just burn a run. Escalating to a human at that point is the correct
outcome, not a failure.

While the retry is in flight, other facts under the same `concept` are paused;
unrelated concepts keep flowing. See `orchestrator.md`.

## Amend format — `previous_values`

**Supersession amends. It never overwrites.** The current `value` changes; the
old one moves into history, with the evidence that supported it.

```yaml
value: <the new current claim>
last_confirmed: <date>
previous_values:
  - value: <the superseded claim>
    source_url: <string>          # what supported it at the time
    source_date: <date|null>      # that source's own publish date
    trust_score: <int>            # its score at the time, not recomputed
    superseded_on: <date>         # when this system replaced it
```

Append to the end of the array. Order is chronological. Entries are never
rewritten, reordered, or removed.

**Why it matters.** "When did the minimum bid change?" is answerable only if the
history survives. Dropping `previous_values` to keep documents tidy destroys the
one thing that makes this a knowledge *acquisition* system rather than a snapshot.

`trust_score` in a history entry is the score **at the time**. Do not recompute
it against the current trusted-domain list — a historical record scored by
today's list is not a historical record.

## `flagged_conflict` format

Written only after the retry has failed. Both claims survive, side by side,
neither marked correct.

```yaml
conflict: true
value: <the incumbent claim — kept as current, but see below>
conflict_with:
  value: <the competing claim>
  source_url: <string>
  source_date: <date|null>
  trust_score: <int>
  official: <bool>
flagged_on: <date>
```

The incumbent stays in `value` because something has to be there and the new
claim has not earned the position. **This is not a verdict.** `conflict: true` is
the operative field: it says this document is under dispute and should not be
trusted until reviewed.

**A flagged document stays readable.** It is surfaced with its warning, never
hidden from whatever consumes `knowledge/`.

Excluding it would be the worse failure: the document still holds the incumbent
value, its full citation list, and its history, and a consumer that silently sees
nothing cannot tell "no knowledge exists" from "knowledge exists but is disputed."
`conflict: true` is the contract — anything reading `knowledge/` is expected to
check it and show the dispute rather than assert the value.

### Body rendering

Publish writes a clearly-marked section for a human adjudicator: both values,
both sources, both trust scores, both dates, stated plainly.

Do not editorialize toward the more trusted source, and do not bury the
disagreement in prose. The entry exists precisely because the system could not
resolve it — writing it as though it leans one way defeats the purpose.

The assignment's "when sources disagree, trust the official ones and note it"
lives in `trust-scoring`, as a score difference the reviewer can see. It is
input to the human's decision, not a substitute for it.

## Notification

Merge writes the entry **silently**. The orchestrator fires the notification once
the write is confirmed — it drove the retry and already knows.

A `flagged_conflict` is one of only three things in this system that interrupts a
human. It should be rare, and it should always be worth reading.
