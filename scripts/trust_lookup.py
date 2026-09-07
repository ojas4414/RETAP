#!/usr/bin/env python3
"""Baseline trust score for a source domain. The code half of trust-scoring.

The rule this script exists to enforce: a source's trustworthiness comes from
a maintained LIST, not from an LLM reasoning about it fresh each time. Validate
adjusts the number this returns by at most +/-10 for context (recency,
corroboration, contradiction history) — it never replaces it.

Bands (see .claude/skills/trust-scoring.md):

    official           85-95   first-party Amazon Ads documentation
    known_unofficial   40-60   established third parties with a track record
    unlisted           10-20   unknown domain, scored low PENDING REVIEW

An unlisted domain is not a rejection. It is an unknown, and it should be
flagged for list maintenance rather than silently accepted or silently binned.

Usage:
    python trust_lookup.py URL [--json]
"""

import argparse
import json
import sys
from urllib.parse import urlparse

BANDS = {
    "official": {"min": 85, "max": 95, "default": 90},
    "known_unofficial": {"min": 40, "max": 60, "default": 50},
    "unlisted": {"min": 10, "max": 20, "default": 15},
}

MAX_CONTEXTUAL_ADJUSTMENT = 10  # Validate may move the baseline by at most this.

# --------------------------------------------------------------------------
# The trusted-domain list.
#
# Shape:  "<domain>" or "<domain>/<path prefix>": (band, score, official)
#   - a bare domain matches the host or any subdomain of it, so
#     "amazon.com" would also cover "advertising.amazon.com".
#   - a path-scoped key matches only URLs whose path starts with that prefix,
#     on a segment boundary. It outranks a bare-domain entry for the same host.
#   - score must sit inside its band's range; validated on load below.
#
# This list is deliberately short. Expanding it as real sources turn up during
# actual runs is expected and healthy — a starter list that grows is the point,
# not a sign of an incomplete one. What is NOT healthy is adding a domain
# silently: an unlisted source is flagged for review precisely so a human
# decides what earns a place here.
# --------------------------------------------------------------------------
TRUSTED_DOMAINS: dict[str, tuple[str, int, bool]] = {
    "advertising.amazon.com": ("official", 92, True),
    "developer.amazon.com":   ("official", 88, True),
    "ppc.sellercentral.com":  ("known_unofficial", 50, True),
    # First-party Amazon GitHub org (e.g. amzn/ads-advanced-tools-docs).
    # Path-scoped on purpose: github.com as a whole is not official, so any
    # other org under it still falls through to unlisted.
    "github.com/amzn":        ("official", 85, True),
    # Raw file host for the same first-party org. Without this, the identical
    # content scores 85 as a rendered page and 15 as a raw file - the sort of
    # inconsistency the list exists to prevent.
    "raw.githubusercontent.com/amzn": ("official", 85, True),
}


def _validate_list() -> None:
    """A score outside its band is a config bug. Fail loudly, at import."""
    for domain, (band, score, _official) in TRUSTED_DOMAINS.items():
        if band not in BANDS:
            raise ValueError(f"{domain}: unknown band {band!r}")
        low, high = BANDS[band]["min"], BANDS[band]["max"]
        if not low <= score <= high:
            raise ValueError(f"{domain}: score {score} outside {band} band {low}-{high}")


_validate_list()


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _path_of(url: str) -> str:
    """Normalized path: leading slash, no trailing slash. '' for the root."""
    path = urlparse(url).path or ""
    return "/" + path.strip("/")  if path.strip("/") else ""


def _path_matches(prefix: str, path: str) -> bool:
    """Segment-boundary prefix match.

    '/amzn' matches '/amzn' and '/amzn/repo' but NOT '/amzn-other' — a
    substring match here would hand an unrelated org an official score.
    """
    return path == prefix or path.startswith(prefix + "/")


def lookup(url: str) -> dict:
    """Baseline lookup. Deterministic: same URL in, same score out.

    Resolution order:
      1. Longest host suffix (sub.example.com before example.com).
      2. Within a host, longest matching path prefix.
      3. A path-scoped entry outranks a bare-domain entry for the same host.

    A host with path-scoped entries but no matching path is NOT a match — it
    falls through to unlisted, which is what keeps github.com/<other-org> from
    inheriting a first-party score.
    """
    domain = domain_of(url)
    path = _path_of(url)
    parts = domain.split(".") if domain else []

    for i in range(len(parts)):
        host = ".".join(parts[i:])

        # Path-scoped entries for this host, longest prefix first.
        scoped = sorted(
            ((k, v) for k, v in TRUSTED_DOMAINS.items() if k.startswith(host + "/")),
            key=lambda kv: len(kv[0]), reverse=True,
        )
        for key, (band, score, official) in scoped:
            prefix = "/" + key[len(host) + 1:].strip("/")
            if _path_matches(prefix, path):
                return {
                    "url": url, "domain": domain, "matched": key,
                    "listed": True, "band": band, "baseline": score,
                    "official": official, "flag_for_review": False,
                }

        # Bare-domain entry for this host.
        if host in TRUSTED_DOMAINS:
            band, score, official = TRUSTED_DOMAINS[host]
            return {
                "url": url, "domain": domain, "matched": host,
                "listed": True, "band": band, "baseline": score,
                "official": official, "flag_for_review": False,
            }

    return {
        "url": url, "domain": domain, "matched": None,
        "listed": False, "band": "unlisted",
        "baseline": BANDS["unlisted"]["default"],
        "official": False,
        # Unlisted is not a verdict. A human decides what belongs on the list.
        "flag_for_review": True,
    }


def clamp(score: int) -> int:
    """Adjusted scores stay in 0-100. Clamp, don't wrap."""
    return max(0, min(100, score))


def main() -> int:
    ap = argparse.ArgumentParser(description="Baseline trust score for a URL.")
    ap.add_argument("url")
    ap.parse_args()
    print(json.dumps(lookup(sys.argv[1]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
