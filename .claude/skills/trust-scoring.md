---
name: trust-scoring
description: >-
  How much a source deserves to be believed — the 0-100 trust_score scale, the
  baseline bands from the maintained trusted-domain list, and the bounded
  contextual adjustments applied on top. Reach for this when scoring a source,
  when interpreting a trust_score already in an OKF document, when a source
  appears whose domain isn't on the list, or when deciding whether a
  corroborating source is strong enough to count. Validate uses it on every
  candidate fact; Merge reads the resulting score for the corroboration floor.
---

# Trust scoring

## The scale

**`trust_score` is an integer, 0-100.** Higher is more trustworthy.

`validate.md` types it `<float>` — that is the general schema type, not a scale
statement. In practice it is always an integer in this range. Anything else is a
bug, and `CORROBORATION_TRUST_FLOOR: 15` is meaningless against a 0-1 float.

## Baseline first, adjustment second

The rule that governs everything below: **the baseline comes from a code lookup
against a maintained list; judgment moves it, judgment never replaces it.**

Never reason a source's trustworthiness from scratch. A source's category is a
fact about the world that a list records — not something to re-derive per fact,
inconsistently, at LLM temperature.

## Step 1 — baseline (code)

`scripts/trust_lookup.py` looks the source's domain up against the maintained
trusted-domain list and returns a baseline.

| Band | Range | What lands here |
|---|---|---|
| Official | 85-95 | First-party Amazon Ads documentation, API references, changelogs, official help centre. |
| Known unofficial | 40-60 | Established third-party sources with a track record — a well-known agency blog, a reputable trade publication. |
| Unlisted | 10-20 | Any domain the list does not cover. Low **pending review**, not low as a verdict. |

An unlisted domain is not a rejection. It is an unknown, scored conservatively
until the list says otherwise — see list maintenance below.

The list itself lives in `scripts/trust_lookup.py`. This file governs what the
bands *mean*; the script holds which domains are in them.

Entries may be bare domains (`advertising.amazon.com`, matching the host and any
subdomain) or **path-scoped** (`github.com/amzn`, matching only that path prefix
on a segment boundary). Path-scoped entries outrank bare-domain ones for the same
host, and a host with path-scoped entries but no matching path falls through to
unlisted — which is how `github.com/<other-org>` avoids inheriting a first-party
score.

The starter list is deliberately short. Growing it as real sources turn up during
runs is expected and healthy.

## Step 2 — contextual adjustment (judgment)

Nudge the baseline within **±10 points total**. Not per factor — total.

| Factor | Direction |
|---|---|
| Recency | Recent publication or confirmation nudges up; a source years stale nudges down. |
| Corroboration | Other independent sources agreeing nudges up. |
| Contradiction history | This source having been wrong before, per `previous_values` and past `flagged_conflict` entries, nudges down. |

The bound is what keeps the baseline dominant. A ±10 window cannot move an
official doc below a blog, or lift an unknown domain into the official band —
which is exactly the point. If a source seems to warrant more movement than that,
the honest fix is the list, not the adjustment.

Adjusted scores stay in 0-100. Clamp, don't wrap.

## List maintenance

When a source appears whose domain the list does not cover, or whose *type* it
was never designed for, **flag it for review**. Do not silently add it, and do
not silently reject it.

The worked example: a GitHub repository hosting an official Amazon Ads MCP
server. The domain is `github.com`, which is not an official Amazon property —
but the repo is first-party. A domain lookup alone gets this wrong in both
directions, and no amount of ±10 nudging fixes a category error. That is a
judgment call about what belongs on the list, and it belongs to a human.

Deciding what goes on the list is judgment. Reading the list is code. Keeping
those separate is the whole design.

## Where the score goes

- Every Validate verdict carries `trust_score`, uniformly — see `validate.md`.
- Merge compares it against `corroboration_trust_floor` to decide whether a new
  source bumps `confirmed_by` — see `merge.md`.
- It is stored twice in an OKF document: once as the fact's current
  `trust_score`, and once per citation in `sources[].trust_score`, recording the
  score **at retrieval time**. Historical scores are never retroactively rewritten
  when the list changes.
