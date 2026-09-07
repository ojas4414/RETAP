#!/usr/bin/env python3
"""orchestrator-write-scope — the orchestrator writes to logs/, nowhere else.

orchestrator.md grants Write so the run log has an owner. Its toolbox section
says that access is "restricted to logs/ only — enforced by a hook, not by this
prose." This is that hook.

Verified empirically against Claude Code 2.1.261 rather than assumed:

  - PreToolUse hooks DO fire for subagent-originated tool calls, not only
    main-session ones. A Write issued inside a Task subagent reaches this hook.
  - The payload carries `agent_type`, holding the agent's frontmatter `name`
    (e.g. "orchestrator", "publish").
  - For a MAIN-SESSION tool call the key is ABSENT entirely — not null, not
    "main". So `agent_type` missing means "not a subagent", and identity checks
    must use .get() rather than assuming the key exists.

Two rules, both scoped to the orchestrator and nobody else:

  1. A Write outside logs/ is blocked.
  2. A Bash command that is not a clock read is blocked. The orchestrator holds
     Bash for exactly one reason - stamping real timestamps on log events
     instead of inventing them - and that is the whole of its shell access.

Every other agent is none of this hook's business: Merge is scoped to staging/
and Publish to knowledge/ by their own definitions, and knowledge/ has its own
gate in validate_before_write.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hooklib import read_event, allow, block, target_path, project_root, under  # noqa: E402

ORCHESTRATOR = "orchestrator"
LOG_SUFFIXES = (".jsonl", ".log")

# The only shell command the orchestrator may run. Reading the clock is not a
# pipeline operation, which is why it does not belong in a stage.
CLOCK_COMMAND = "date"


def main() -> None:
    event = read_event()

    # Absent for main-session calls; the agent's frontmatter name otherwise.
    if event.get("agent_type") != ORCHESTRATOR:
        allow()

    # --- Bash: clock reads only -------------------------------------------
    if event.get("tool_name") == "Bash":
        command = ((event.get("tool_input") or {}).get("command") or "").strip()
        if command.split(" ")[0] != CLOCK_COMMAND:
            block(
                "orchestrator-write-scope: the orchestrator may only run "
                "'{}' (reading the clock for log timestamps). Refused: {!r}. "
                "Every other shell operation belongs in a stage - Discover runs "
                "the fetch/hash/clean scripts.".format(CLOCK_COMMAND, command[:80])
            )
        allow()

    path = target_path(event)
    if path is None:
        allow()

    logs = project_root(event) / "logs"

    if not under(path, logs):
        block(
            "orchestrator-write-scope: the orchestrator may only write under "
            "logs/. Refused: {}. This write belongs in a pipeline stage: "
            "Merge writes staging, Publish writes knowledge/.".format(path)
        )

    if path.suffix not in LOG_SUFFIXES:
        block(
            "orchestrator-write-scope: logs/ holds run logs only "
            "({}). Refused: {}".format(" / ".join(LOG_SUFFIXES), path.name)
        )

    allow()


if __name__ == "__main__":
    main()
