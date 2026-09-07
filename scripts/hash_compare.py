#!/usr/bin/env python3
"""Content hashing and comparison against the last run. Discover's step 7.

Also owns every deterministic write to the source registry
(knowledge/.sources.json), because "did this change" and "record that we
looked" are the same operation seen from two sides.

Registry shape:

    {
      "version": 1,
      "sources": {
        "<source_id>": {
          "url": "https://...",
          "official": true,
          "fetch_method": "static" | "js_rendered",
          "fetch_method_last_probed": "2026-09-06T00:00:00Z" | null,
          "content_hash": "<sha256 of cleaned content>" | null,
          "last_checked": "2026-09-06T00:00:00Z" | null,
          "consecutive_failures": 0
        }
      }
    }

Two failure signals live here and must never be conflated (see discover.md):
`fail` increments consecutive_failures (the page did not come back);
`method` records JS-rendering, which is not a failure at all.

Usage:
    python hash_compare.py hash [FILE]
    python hash_compare.py compare SOURCE_ID FILE [--update]
    python hash_compare.py fail SOURCE_ID
    python hash_compare.py method SOURCE_ID static|js_rendered
    python hash_compare.py reset SOURCE_ID
    python hash_compare.py get SOURCE_ID
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REGISTRY = Path("knowledge/.sources.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "sources": {}}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")


def get_source(registry: dict, source_id: str) -> dict:
    return registry.setdefault("sources", {}).setdefault(source_id, {
        "url": None, "official": False, "fetch_method": "static",
        "fetch_method_last_probed": None, "content_hash": None,
        "last_checked": None, "consecutive_failures": 0,
    })


def read_text(path: str | None) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def cmd_hash(args) -> int:
    print(json.dumps({"sha256": sha256_text(read_text(args.file))}, indent=2))
    return 0


def cmd_compare(args) -> int:
    """Compare cleaned content against the stored hash.

    `--update` records the new hash, bumps last_checked, and resets
    consecutive_failures — a successful fetch, by definition.
    """
    digest = sha256_text(read_text(args.file))
    registry = load_registry(args.registry)
    source = get_source(registry, args.source_id)
    previous = source.get("content_hash")

    if previous is None:
        status = "new"
    elif previous == digest:
        status = "unchanged"
    else:
        status = "changed"

    if args.update:
        source["content_hash"] = digest
        source["last_checked"] = utc_now()
        source["consecutive_failures"] = 0
        save_registry(args.registry, registry)

    print(json.dumps({
        "source_id": args.source_id, "status": status,
        "content_hash": digest, "previous_hash": previous,
        "updated": bool(args.update),
    }, indent=2))
    return 0


def cmd_fail(args) -> int:
    """Record an outright fetch failure. NOT for the usable-content check."""
    registry = load_registry(args.registry)
    source = get_source(registry, args.source_id)
    source["consecutive_failures"] = int(source.get("consecutive_failures", 0)) + 1
    source["last_checked"] = utc_now()
    save_registry(args.registry, registry)
    print(json.dumps({
        "source_id": args.source_id, "status": "failed",
        "consecutive_failures": source["consecutive_failures"],
    }, indent=2))
    return 0


def cmd_method(args) -> int:
    """Memoize the fetch method and reset the recheck timer."""
    registry = load_registry(args.registry)
    source = get_source(registry, args.source_id)
    source["fetch_method"] = args.fetch_method
    source["fetch_method_last_probed"] = utc_now()
    save_registry(args.registry, registry)
    print(json.dumps({
        "source_id": args.source_id, "fetch_method": args.fetch_method,
        "fetch_method_last_probed": source["fetch_method_last_probed"],
    }, indent=2))
    return 0


def cmd_reset(args) -> int:
    """Mark an interrupted source capture for explicit reprocessing.

    A failed run may have captured and hashed source content before a downstream
    stage halts. Clearing only the processed hash preserves the source URL,
    fetch-method memoization and failure history, while ensuring the next
    Discover pass treats the source as a first capture again.
    """
    registry = load_registry(args.registry)
    source = get_source(registry, args.source_id)
    previous = source.get("content_hash")
    source["content_hash"] = None
    save_registry(args.registry, registry)
    print(json.dumps({
        "source_id": args.source_id,
        "status": "reset",
        "previous_hash": previous,
    }, indent=2))
    return 0


def cmd_get(args) -> int:
    registry = load_registry(args.registry)
    source = registry.get("sources", {}).get(args.source_id)
    if source is None:
        print(json.dumps({"source_id": args.source_id, "found": False}, indent=2))
        return 1
    print(json.dumps({"source_id": args.source_id, "found": True, **source}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Hashing and source-registry bookkeeping.")
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hash", help="sha256 of a file or stdin")
    p.add_argument("file", nargs="?", default="-")
    p.set_defaults(func=cmd_hash)

    p = sub.add_parser("compare", help="compare cleaned content against last run")
    p.add_argument("source_id")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--update", action="store_true")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("fail", help="record an outright fetch failure")
    p.add_argument("source_id")
    p.set_defaults(func=cmd_fail)

    p = sub.add_parser("method", help="memoize static | js_rendered")
    p.add_argument("source_id")
    p.add_argument("fetch_method", choices=["static", "js_rendered"])
    p.set_defaults(func=cmd_method)

    p = sub.add_parser("reset", help="clear a hash so an interrupted source is reprocessed")
    p.add_argument("source_id")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("get", help="read one source's registry entry")
    p.add_argument("source_id")
    p.set_defaults(func=cmd_get)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
