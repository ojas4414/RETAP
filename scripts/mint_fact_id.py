#!/usr/bin/env python3
"""Mint a deterministic identifier for a newly staged fact.

The ID belongs in deterministic code, not in Merge's judgment. Given the same
concept and value, this command always returns the same identifier:

    <concept>-<first 8 hex chars of sha256("<concept>:<value>")>

Usage:
    python scripts/mint_fact_id.py CONCEPT VALUE
"""

import argparse
import hashlib
import json


def mint_fact_id(concept: str, value: str) -> str:
    """Return the stable ID for a fact's concept and value."""
    digest_input = "{}:{}".format(concept, value)
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:8]
    return "{}-{}".format(concept, digest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a deterministic fact ID.")
    parser.add_argument("concept")
    parser.add_argument("value")
    args = parser.parse_args()

    print(json.dumps({
        "concept": args.concept,
        "value": args.value,
        "fact_id": mint_fact_id(args.concept, args.value),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
