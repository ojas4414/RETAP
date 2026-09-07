"""Shared plumbing for this project's PreToolUse hooks.

A PreToolUse hook receives the tool call as JSON on stdin:

    {"session_id": ..., "cwd": ..., "hook_event_name": "PreToolUse",
     "tool_name": "Write", "tool_input": {...}}

and decides whether it proceeds:

    exit 0  -> allow
    exit 2  -> BLOCK. stderr goes back to the model as the reason.

Hooks are the enforcement layer for rules that prose in an agent file cannot
enforce. Anything here fails CLOSED on a rule violation and OPEN on its own
internal error — a broken hook must not wedge the pipeline.
"""

import json
import re
import sys
from pathlib import Path


def read_event() -> dict:
    """Parse the hook payload. On malformed input, allow — see module docstring."""
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)


def allow() -> None:
    sys.exit(0)


def block(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def target_path(event: dict):
    """The file a write-ish tool is aiming at, as an absolute path."""
    raw = (event.get("tool_input") or {}).get("file_path")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = Path(event.get("cwd") or ".") / p
    try:
        return p.resolve()
    except Exception:
        return p


def under(path: Path, root: Path) -> bool:
    """True if path sits inside root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def project_root(event: dict) -> Path:
    return Path(event.get("cwd") or ".").resolve()


# ---------------------------------------------------------------------------
# The <PAYLOAD> convention
#
# A Task payload is prompt text, not a typed struct, so structured data needs an
# agreed location inside that text or a hook cannot find it to validate it.
# Every Task call carrying structured data wraps it in delimiters:
#
#     <PAYLOAD>
#     { ...json... }
#     </PAYLOAD>
#
# Markers absent -> the call carries no structured data. That is legitimate
# (a plain instruction), and validation does not apply.
# ---------------------------------------------------------------------------

PAYLOAD_RE = re.compile(r"<PAYLOAD>(.*?)</PAYLOAD>", re.DOTALL)

# The five verdicts Validate may emit, and the fields each requires.
# Mirrors validate.md; if these drift apart, validate.md is authoritative.
VERDICT_FIELDS = {
    "new": {"trust_score"},
    "duplicate_exact": {"matches", "trust_score"},
    "duplicate_corroborating": {"matches", "new_source", "trust_score", "independent"},
    "contradiction": {"conflicts_with", "trust_score"},
    "supersession": {"replaces", "trust_score"},
}

# Statuses Publish may legitimately be handed. `duplicate_exact` is absent on
# purpose: Merge stops on it, so it must never reach Publish.
PUBLISH_STATUSES = {"new", "duplicate_corroborating", "supersession", "flagged_conflict"}

# Some stage invocations are NOT verdict handoffs. A mode call carries no verdict
# by design, so validating it as one blocks it on every run - which happened
# twice, to two different stages, before this existed.
#
#   publish/resolve_links -> the end-of-run pending-link pass. Nothing is being
#                            published; a marker is resolved in an existing doc.
#   merge/resume_check    -> enumerate staging/ for status:"paused" records at
#                            the start of a run. "Nothing is paused" is not a
#                            new/duplicate/contradiction/supersession verdict.
STAGE_MODES = {
    "publish": {"resolve_links"},
    "merge": {"resume_check"},
}

# Kept for readers who reach for it by the older name.
PUBLISH_MODES = STAGE_MODES["publish"]

# Required top-level fields per target stage. Config values appear here because
# of the config-flow rule: config lives in orchestrator.md and travels on the
# Task payload, so a missing one is a malformed payload, never a default to
# silently assume.
STAGE_SCHEMAS: dict[str, set[str]] = {
    "discover": {"fetch_method_recheck_days"},
    # `content_path`, not inline `content`: Discover writes cleaned text to a
    # file and reports where. Extract holds Read and opens it itself. The
    # orchestrator has no Read, so it cannot inline the text even in principle -
    # and payloads stay small instead of carrying whole documents.
    "extract": {"source_id", "content_path", "concept_index"},
    "validate": {"candidate", "stored_facts", "staleness_threshold_days"},
    "merge": {"status"},
    "publish": {"changed_fields"},
}

# Nested requirements, checked only when the parent field is present.
NESTED_SCHEMAS: dict[str, dict[str, set[str]]] = {
    "validate": {"candidate": {"concept", "value", "source_id", "source_date"}},
}


def extract_payload(prompt: str):
    """Return (found, parsed_or_error).

    (False, None)      -> no payload here; nothing to validate.
    (True, dict)       -> parsed payload.
    (True, str)        -> markers present, content is meant to be JSON, and
                          isn't; the string is the parse error.

    Prose that merely *describes* the convention is not a payload. Documentation,
    a prompt explaining the format, an agent quoting the markers while reasoning
    about them - all of these contain the marker text without carrying data, and
    blocking them would make the convention impossible to talk about. This bit
    two real invocations before the heuristic existed.

    HEURISTIC, and it is worth being honest that it is one: content whose first
    non-whitespace character is `{` or `[` is treated as an intended payload, so
    a genuine malformed payload still blocks. Anything else is read as prose and
    allowed through unvalidated.

    Its limit: prose that happens to begin with a brace is still treated as a
    payload and will block, and a payload wrapped in a stray explanatory sentence
    before the brace is read as prose and skipped. Both are narrow, and the
    failure directions are the safe ones - a false block is visible and loud, and
    a false skip only loses validation on a call that was already unconventional.
    """
    if not prompt:
        return False, None
    match = PAYLOAD_RE.search(prompt)
    if not match:
        return False, None

    body = match.group(1).strip()
    if not body.startswith(("{", "[")):
        return False, None  # descriptive prose, not data

    try:
        return True, json.loads(body)
    except Exception as exc:
        return True, "not valid JSON: {}".format(exc)


# Full ISO-8601 UTC, second precision - the shape `date -u +%Y-%m-%dT%H:%M:%SZ`
# produces. A bare date is not a lax version of this, it is a different thing:
# two runs on the same day must be orderable, and `2026-09-06` cannot say which
# of them confirmed a value.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Fields this system generates itself, so it controls their format. A source's
# own `published` date is deliberately absent: that is copied from the source,
# whatever shape the source states, and is null when it states none.
TIMESTAMP_FIELDS = ("last_confirmed", "superseded_on", "flagged_on",
                    "last_checked", "fetch_method_last_probed")


def bad_timestamps(payload: dict):
    """Timestamp fields must be full ISO-8601 UTC, not bare dates.

    Checks the payload's own fields and one level into a `facts` list, which is
    where multi-fact documents carry their per-fact values.
    """
    problems = []

    def check(obj, prefix=""):
        if not isinstance(obj, dict):
            return
        for field in TIMESTAMP_FIELDS:
            value = obj.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
                problems.append(
                    "{}{} must be ISO-8601 UTC like 2026-09-06T16:07:41Z "
                    "(got {!r})".format(prefix, field, value))

    check(payload)
    for i, fact in enumerate(payload.get("facts") or []):
        check(fact, "facts[{}].".format(i))
    return problems


def bad_trust_score(payload: dict):
    """trust_score must be an integer 0-100. See the trust-scoring skill.

    Catches the 0-1 float a stage produces when it reasons the scale instead of
    reading it - which happened, and was patched over mid-run by prompt.
    """
    if "trust_score" not in payload:
        return None
    value = payload["trust_score"]
    if isinstance(value, bool) or not isinstance(value, int):
        return "trust_score must be an integer 0-100 (got {!r})".format(value)
    if not 0 <= value <= 100:
        return "trust_score must be within 0-100 (got {})".format(value)
    return None


def missing_fields(stage: str, payload: dict) -> list[str]:
    """Required fields absent from `payload` for `stage`. Empty list = valid."""
    if not isinstance(payload, dict):
        return ["<payload is not a JSON object>"]

    # Mode calls short-circuit: they are not verdict handoffs and carry none of
    # a verdict's fields.
    if stage in STAGE_MODES:
        mode_result = _mode_call(stage, payload)
        if mode_result is not None:
            return mode_result

    missing = sorted(STAGE_SCHEMAS.get(stage, set()) - set(payload))

    for parent, required in NESTED_SCHEMAS.get(stage, {}).items():
        child = payload.get(parent)
        if isinstance(child, dict):
            missing += sorted("{}.{}".format(parent, f) for f in required - set(child))

    # Merge is handed a verdict: which fields are required depends on which
    # status it carries.
    bad_score = bad_trust_score(payload)
    if bad_score:
        return [bad_score]

    stamps = bad_timestamps(payload)
    if stamps:
        return stamps

    if stage == "merge" and "status" in payload:
        status = payload["status"]
        if status not in VERDICT_FIELDS:
            return ["status=<one of {}> (got {!r})".format(
                "|".join(sorted(VERDICT_FIELDS)), status)]
        missing += sorted(VERDICT_FIELDS[status] - set(payload))

    # Publish is handed Merge's verdict; Merge names the field `verdict_status`.
    if stage == "publish":
        status = payload.get("verdict_status", payload.get("status"))
        if status is None:
            missing.append("verdict_status")
        elif status not in PUBLISH_STATUSES:
            return ["verdict_status=<one of {}> (got {!r})".format(
                "|".join(sorted(PUBLISH_STATUSES)), status)]

    return missing


def _mode_call(stage: str, payload: dict):
    """A mode call is validated on its own terms, not as a verdict.

    Returns None when this is not a mode call at all, [] when it is a valid one,
    and a reason list when the mode is unrecognized. An unknown mode still
    blocks - modes got their own schema, not an exemption from having one.
    """
    mode = payload.get("mode")
    if mode is None:
        return None
    allowed = STAGE_MODES.get(stage, set())
    if mode not in allowed:
        return ["mode=<one of {}> (got {!r})".format(
            "|".join(sorted(allowed)) or "<none defined for this stage>", mode)]
    return []
