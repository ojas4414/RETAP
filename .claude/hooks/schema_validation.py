#!/usr/bin/env python3
"""schema-validation - reject malformed payloads at every stage handoff.

Fires on every Task call between pipeline stages. This is what lets the
orchestrator watch run *health* without also reasoning about payload
correctness: a stage never sees a payload that fails its schema, because this
hook rejected it first.

Fully code-level. No exceptions, no LLM judgment. That is the point.

Structured data travels inside the prompt wrapped in <PAYLOAD>...</PAYLOAD>
markers - see _hooklib.py, which holds the schemas so they are declared once
and shared with validate_before_write.py.

Failure policy:
  rule violation    -> BLOCK (exit 2), naming the missing field
  no markers        -> ALLOW (a plain instruction carries no payload)
  internal error    -> ALLOW (a broken hook must never wedge the pipeline)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hooklib import (  # noqa: E402
    read_event, allow, block, extract_payload, missing_fields, STAGE_SCHEMAS,
)


def main() -> None:
    event = read_event()
    tool_input = event.get("tool_input") or {}

    stage = tool_input.get("subagent_type")
    found, payload = extract_payload(tool_input.get("prompt") or "")

    if not found:
        allow()  # no structured data in this call; nothing to check

    if isinstance(payload, str):
        block(
            "schema-validation: <PAYLOAD> block is present but malformed - {}. "
            "Structured Task data must be valid JSON between the markers."
            .format(payload)
        )

    if stage not in STAGE_SCHEMAS:
        allow()  # not a pipeline stage; not this hook's business

    missing = missing_fields(stage, payload)
    if missing:
        block(
            "schema-validation: payload for '{}' is missing required field(s): "
            "{}. Config values travel on the Task payload (orchestrator.md owns "
            "them) and are never defaulted silently."
            .format(stage, ", ".join(missing))
        )

    allow()


if __name__ == "__main__":
    main()
