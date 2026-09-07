#!/usr/bin/env python3
"""Plain HTTP fetch. The default fetch path for Discover.

Deterministic: no interpretation, no judgment, no retries with different
strategies. Fetch the URL, report what came back, exit.

Discover uses the exit code to distinguish its two failure signals:

    0   the page came back. Whether it is *usable* (JS-rendering check) is
        Discover's next step, not this script's business.
    1   outright fetch failure — network error, timeout, 4xx/5xx. This is the
        signal that increments `consecutive_failures` in the registry.

Usage:
    python fetch_url.py URL [--out FILE] [--timeout SECONDS]

Metadata JSON always goes to stdout. The body goes to --out when given,
otherwise into the JSON's "body" field.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_TIMEOUT = 30
DEFAULT_UA = "amazon-ads-kb/0.1 (knowledge acquisition; contact: repo owner)"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_UA) -> dict:
    """Fetch a URL. Raises urllib errors; the caller decides what they mean."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return {
            "url": url,
            "final_url": resp.geturl(),
            "status": resp.status,
            "content_type": resp.headers.get("Content-Type", ""),
            "last_modified": resp.headers.get("Last-Modified"),
            "bytes": len(raw),
            "fetched_at": utc_now(),
            "body": raw.decode(charset, errors="replace"),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Plain HTTP fetch for Discover.")
    ap.add_argument("url")
    ap.add_argument("--out", help="write the body here instead of into the JSON")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    args = ap.parse_args()

    try:
        result = fetch(args.url, args.timeout, args.user_agent)
    except urllib.error.HTTPError as e:
        json.dump({"url": args.url, "status": e.code, "ok": False,
                   "error": f"HTTP {e.code} {e.reason}", "fetched_at": utc_now()},
                  sys.stdout, indent=2)
        print()
        return 1
    except Exception as e:  # URLError, timeout, DNS, TLS, decode
        json.dump({"url": args.url, "status": None, "ok": False,
                   "error": f"{type(e).__name__}: {e}", "fetched_at": utc_now()},
                  sys.stdout, indent=2)
        print()
        return 1

    body = result.pop("body")
    result["ok"] = True
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        result["body_path"] = args.out
    else:
        result["body"] = body

    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
