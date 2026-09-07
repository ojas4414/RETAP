---
name: citation-rules
description: >-
  What counts as a valid citation, the hard "no citation, no publish" rule,
  and how multiple corroborating sources are recorded and counted. Reach for
  this when attaching a source to an extracted fact, when adding a source to
  an existing fact's citation list, when deciding whether confirmed_by should
  move, or before finalizing any document in knowledge/. Used by Extract,
  Validate, Merge, and Publish — every stage that touches a source reference.
---

# Citation rules

Every published fact traces back to where it came from. This is the assignment's
"every fact should trace back to its source," and it is enforced, not encouraged.

## The hard rule

**No citation, no publish.**

A fact that cannot be cited does not get written to `knowledge/`. Not written
with a caveat, not written pending a source — not written.

This binds at both ends of the pipeline: Extract should not emit a fact it cannot
attribute, and Publish must not finalize a document that fails this check. A fact
arriving at Publish uncitable means something upstream is broken, and the right
response is to fail loudly rather than publish a fact with no provenance.

## Minimum valid citation

Two fields. Both required. No exceptions:

```yaml
- url: <string>          # the retrievable source URL
  retrieved: <date>      # when Discover last fetched it
```

Anything less is not a citation. "Amazon documentation" is not a citation. A
remembered fact with no URL is not a citation.

## Full citation entry

As stored in an OKF document's `sources` array — see `okf-format`:

```yaml
- url: <string>
  retrieved: <date>          # required
  trust_score: <int>         # 0-100 at retrieval time; see trust-scoring
  official: <bool>           # first-party Amazon source or not
  published: <date|null>     # source's own publish/last-modified date, null if absent
```

`published` is `null` when the source states no date. **Never infer one.** A
guessed date corrupts the staleness trigger that decides when Validate re-verifies.

`trust_score` is recorded at retrieval time and is not retroactively rewritten
when the trusted-domain list changes.

## Multiple sources

The `sources` array holds **every source ever seen** for a fact, in the order
they were first seen. Sources are never removed — a source that once said
something is part of the record, even after it changes or disappears.

### `confirmed_by` is not `len(sources)`

These are different numbers and conflating them is the mistake this section
exists to prevent.

- `sources` — everything seen and checked.
- `confirmed_by` — how many of those actually count as confirmation.

A corroborating source below the corroboration trust floor is **cited without
incrementing `confirmed_by`** (see `merge.md`). So `confirmed_by <= len(sources)`,
always, and the gap between them is meaningful: it says "we saw this claim
elsewhere, but not somewhere we'd stake the count on."

### Independence

`confirmed_by` is supposed to answer "how many *independent* sources back this."
Two URLs are not two confirmations when they are the same source underneath.

Judging that is **not** this skill's job — see `dedup-rules`, which covers source
independence alongside fact-level deduplication. They are the same judgment
("this is the same thing in a different surface form") applied at two levels, and
they feed the same outcome: whether `confirmed_by` legitimately increments.

## Per-stage responsibilities

| Stage | What it owes this skill |
|---|---|
| Extract | Attaches `source_id` and `source_date` to every emitted fact. Emits nothing it cannot attribute. |
| Validate | Carries the source through in the verdict; scores it. |
| Merge | Adds the citation entry; applies the trust floor to decide `confirmed_by`. |
| Publish | Final gate — checks the document has at least one valid citation before writing. |
