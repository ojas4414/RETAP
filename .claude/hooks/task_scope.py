#!/usr/bin/env python3
"""task-scope — Validate may only escalate to Discover.

validate.md says its `Task` access is "scoped to `discover` only". Agent
frontmatter cannot express that: `tools: Task` grants the tool with no way to
constrain which agent it targets. Prose alone is not enforcement.

This is the runtime check the master prompt asked for. It is possible because
`agent_type` is present in the hook payload (verified against 2.1.261 — see
orchestrator_write_scope.py for the evidence).

Rule: a Task call originating inside `validate` must target `discover`. Every
other caller is unconstrained here — the orchestrator legitimately invokes all
five stages.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hooklib import read_event, allow, block  # noqa: E402

CALLER = "validate"
ALLOWED_TARGET = "discover"


def main() -> None:
    event = read_event()

    if event.get("agent_type") != CALLER:
        allow()

    target = (event.get("tool_input") or {}).get("subagent_type")

    if target != ALLOWED_TARGET:
        block(
            "task-scope: validate may only escalate to '{}' (narrow, "
            "single-fact, mid-classification). Refused target: {!r}. Reopening a "
            "completed decision is the orchestrator's call, not validate's."
            .format(ALLOWED_TARGET, target)
        )

    allow()


if __name__ == "__main__":
    main()
