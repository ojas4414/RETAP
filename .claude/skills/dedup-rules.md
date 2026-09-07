---
name: dedup-rules
description: >-
  How to tell `duplicate_exact` from `duplicate_corroborating` from a
  genuinely new fact — and, at the source level, whether a corroborating
  source is actually independent of ones already cited. Reach for this when
  classifying a candidate fact against stored facts, when two facts say the
  same thing in different words, when deciding whether confirmed_by should
  increment, or when a new source looks like a mirror or republish of an
  existing one. Validate's primary reference; Merge reads the independence
  outcome.
---

# Dedup rules

Two levels of one judgment: **is this the same thing wearing a different surface
form?**

- **Fact level** — same claim, different wording.
- **Source level** — same source, different URL.

Both feed the same downstream outcome: whether `confirmed_by` legitimately
increments. They live in one skill because splitting them would split a single
judgment across two files.

---

# Part 1 — fact-level deduplication

## Step 1: the code pre-filter (no LLM call)

Runs first, always. Compare the candidate against stored facts **of the same
concept only**.

Normalize both sides, then compare:

- lowercase
- collapse runs of whitespace
- strip leading/trailing whitespace and trailing punctuation

Identical after normalization -> **`duplicate_exact`**, immediately. No judgment
invoked, no tokens spent.

This filter catches the overwhelmingly common case: an unchanged page re-fetched
and re-extracted. Skipping it and asking an LLM "are these the same?" thousands
of times is the expensive mistake this design exists to avoid.

Normalization also **strips markdown emphasis** (`**bold**`, `_italic_`) and
**unwraps inline links** to their text. Presentation is not content: a doc page
that bolds a number this month has not changed the number. Letting formatting
drift fall through to semantic judgment would spend an LLM call to conclude
"yes, `$0.02` and `**$0.02**` are the same" — which is exactly the class of
question this pre-filter exists to never ask.

## Step 2: semantic equivalence (judgment)

Only what survives the pre-filter gets here.

**Same fact, different wording** — these are duplicates:

- Reworded or restructured, same claim: "The minimum bid is $0.02" vs. "Bids must
  be at least $0.02."
- Same value, different unit or notation, where the units convert exactly.
- One states the claim, the other states it with a redundant qualifier that
  doesn't narrow it.

**Genuinely different facts** — these are not duplicates, however similar they
look:

- **Different scope.** Same field, different subject: a minimum bid for Sponsored
  Products vs. for Sponsored Display, or for the US marketplace vs. the UK. A
  scope qualifier is part of the fact, not decoration around it.
- **Different precision about different things.** "Reports refresh hourly" and
  "Reports refresh within 12 hours" may both be true of different report types.
- **Compound vs. atomic.** A stored fact carrying two claims is not equivalent to
  a candidate carrying one of them. Flag the compound fact rather than merging
  into it — Extract should have split it.

**When the strings differ non-trivially but mean the same thing**, this is also
where Extract's deliberately-shallow concept reuse gets corrected: `min-bid` and
`minimum-bid-amount` arrive as separate concepts and are recognized as one here.
Extract does cheap string reuse; this is where the real matching happens.

## The same source is never corroboration

Worth stating as its own rule, because it is easy to re-introduce as a bug later:
**a candidate whose `source_id` is already cited for the matching stored fact is
`duplicate_exact`, never `duplicate_corroborating`** — even when the wording
drifted between runs.

A page re-fetched next month with a lightly reworded sentence is one source
saying one thing twice. Routing it to `duplicate_corroborating` would let a
single source increment `confirmed_by` on every re-fetch, and the count would
climb forever while the evidence behind it never grew.

Check `source_id` against the stored fact's existing citations **before** reaching
for semantic judgment. Only a genuinely different source is eligible to
corroborate.

## Verdict mapping

| Situation | Verdict |
|---|---|
| Identical after normalization | `duplicate_exact` |
| Same claim, different wording, new source | `duplicate_corroborating` |
| Same claim, different wording, source already cited | `duplicate_exact` — see above; one source, counted once |
| Same subject, incompatible values | `contradiction` (see `conflict-resolution`) |
| Same subject, newer source, old value was right at its time | `supersession` |
| No stored fact means this | `new` |

---

# Part 2 — source-level independence

Runs **before** a `duplicate_corroborating` lets a new source count toward
`confirmed_by`.

## Why URL comparison is not enough

The fact's wording can match perfectly while the real duplicate is the *source*
underneath it. A mirror republishing an official doc verbatim produces a
character-identical fact from a different URL — fact-level dedup sees a
legitimate second source, and `confirmed_by` inflates on what is really one
source counted twice.

This is judgment, not a code check. Recognizing "these are the same underlying
source" usually requires understanding content overlap, not comparing hostnames.

## Signals of non-independence

- **Mirror or syndication.** Near-verbatim republication of an already-cited
  source, with or without attribution.
- **Same document, different format.** A doc page and its PDF export. A help
  article and its printable version.
- **Same publisher restating itself.** A vendor's blog post and its press release
  making the same announcement are one source's claim, published twice.
- **Aggregator repeating a cited primary source.** A roundup post whose entire
  basis is a doc already in `sources`.

Independent means the source could have been wrong on its own. If it is simply
relaying an already-cited source, it adds reach, not evidence.

## Outcome

Not independent -> **cite it, don't count it.** Add the citation entry, leave
`confirmed_by` unchanged. Same handling as a source below the corroboration trust
floor, and for the same reason: the record keeps everything it saw; the count
stays honest.

Independent -> proceed to Merge's trust-floor check, which may still decline to
count it.

Two gates, in order: **independent?** then **trusted enough?** A source must pass
both to increment `confirmed_by`.

## How the outcome travels

Validate makes this judgment and reports it as `independent: <bool>` on the
`duplicate_corroborating` verdict. Merge reads the field and applies it as gate 1
on `confirmed_by`, without re-litigating it.

The judgment happens once, in the stage that holds both the candidate and the
stored sources. Merge acts on the result.
