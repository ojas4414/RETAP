#!/usr/bin/env python3
"""validate-before-write - nothing reaches knowledge/ without passing Merge.

knowledge/ is the deliverable. A fact lands there only after Validate has
classified it and Merge has acted on that verdict; Publish then renders it.
A write that skips those stages is how unvalidated, uncited knowledge gets in.

Two checks, cheapest first:

  1. IDENTITY. A write under knowledge/ must come from `publish`. Nothing else
     has any business there - Merge writes staging/, Discover writes the
     registry (exempted below), the orchestrator writes logs/. This is the
     check doing the real work, and it is a single dict lookup.

  2. PROVENANCE. Publish is only legitimate when a Merge verdict put it there.
     Walk back through the session transcript to the Task call that spawned
     this Publish, read its <PAYLOAD>, and confirm it carries a Merge-shaped
     verdict. A safety net behind check 1, not a replacement for it.

Exemption: knowledge/.sources.json and other dotfiles. The source registry is
operational bookkeeping Discover maintains every run - it lives under
knowledge/ but is not part of the OKF bundle.

Failure policy:
  rule violation        -> BLOCK (exit 2)
  cannot verify (no transcript, spawning call not found) -> ALLOW
  internal error        -> ALLOW
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hooklib import (  # noqa: E402
    read_event, allow, block, target_path, project_root, under,
    extract_payload, missing_fields,
)

PUBLISHER = "publish"
OKF_ROOTS = ("concepts", "index.md")


def spawning_payload(transcript_path: str):
    """The <PAYLOAD> from the most recent Task call targeting publish.

    Returns None when it cannot be determined - no transcript, unreadable, or
    no such call. The caller treats None as "cannot verify" and allows.
    """
    if not transcript_path:
        return None
    path = Path(transcript_path)
    if not path.exists():
        return None

    latest = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or "subagent_type" not in line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                for block_ in _tool_uses(entry):
                    if block_.get("name") != "Task":
                        continue
                    tin = block_.get("input") or {}
                    if tin.get("subagent_type") != PUBLISHER:
                        continue
                    found, payload = extract_payload(tin.get("prompt") or "")
                    if found and isinstance(payload, dict):
                        latest = payload
    except Exception:
        return None
    return latest


def _tool_uses(entry: dict):
    """Yield tool_use blocks from a transcript entry, whatever its shape."""
    content = (entry.get("message") or {}).get("content") or entry.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                yield item


def main() -> None:
    event = read_event()
    path = target_path(event)
    if path is None:
        allow()

    knowledge = project_root(event) / "knowledge"
    if not under(path, knowledge):
        allow()  # not this hook's jurisdiction

    rel = path.relative_to(knowledge)

    # Exemption: source registry and other operational dotfiles.
    if rel.parts and rel.parts[0].startswith("."):
        allow()

    # --- structural rules -------------------------------------------------
    if rel.parts and rel.parts[0] not in OKF_ROOTS:
        block(
            "validate-before-write: knowledge/ holds the OKF bundle only "
            "(concepts/, index.md). Refused: knowledge/{}".format(rel.as_posix())
        )

    if rel.parts[0] == "concepts" and path.suffix != ".md":
        block(
            "validate-before-write: knowledge/concepts/ holds OKF markdown "
            "documents only. Refused: {}".format(path.name)
        )

    # --- check 1: identity ------------------------------------------------
    agent = event.get("agent_type")
    if agent != PUBLISHER:
        block(
            "validate-before-write: only 'publish' may write to knowledge/. "
            "Caller was {}. Merge writes staging/, Discover writes the registry, "
            "the orchestrator writes logs/.".format(
                "'{}'".format(agent) if agent else "the main session")
        )

    # --- check 2: provenance ----------------------------------------------
    payload = spawning_payload(event.get("transcript_path") or "")
    if payload is None:
        # Cannot verify - the identity check above already did the real work.
        # Failing closed here blocks every legitimate publish whenever the
        # transcript cannot be parsed, which is how a run reached Publish and
        # wrote nothing at all.
        allow()

    missing = missing_fields(PUBLISHER, payload)
    if missing:
        block(
            "validate-before-write: publish was invoked without a valid Merge "
            "verdict behind it - missing {}. A document only reaches knowledge/ "
            "because Merge decided it should.".format(", ".join(missing))
        )

    allow()


if __name__ == "__main__":
    main()
