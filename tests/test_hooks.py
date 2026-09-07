"""Tests for the hooks - the enforcement layer.

A hook is the only thing in this system that can actually stop an agent doing
something its prompt told it not to do. So the rules worth testing are the ones
a hook enforces, and the property worth testing hardest is that each hook fails
CLOSED on a violation and OPEN on its own internal error.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))

import _hooklib  # noqa: E402

ALLOW, BLOCK = 0, 2


def fire(hook, event):
    """Run a hook with an event payload. Returns (exit_code, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(event), capture_output=True, text=True, cwd=str(ROOT))
    return proc.returncode, proc.stderr.strip()


# --------------------------------------------------------------------------
# The PAYLOAD convention, and telling data from prose
# --------------------------------------------------------------------------

def test_real_payload_is_parsed():
    found, payload = _hooklib.extract_payload('go <PAYLOAD>{"a": 1}</PAYLOAD> now')
    assert found and payload == {"a": 1}


@pytest.mark.parametrize("prompt", [
    "Wrap structured data in <PAYLOAD>...</PAYLOAD> markers.",
    "<PAYLOAD>the JSON goes here, per the convention</PAYLOAD>",
])
def test_prose_describing_the_convention_is_not_a_payload(prompt):
    """Documentation must not be mistaken for data - this blocked real runs."""
    found, _ = _hooklib.extract_payload(prompt)
    assert not found


def test_malformed_json_still_blocks():
    found, err = _hooklib.extract_payload("<PAYLOAD>{oops}</PAYLOAD>")
    assert found and isinstance(err, str)


# --------------------------------------------------------------------------
# Stage schemas
# --------------------------------------------------------------------------

def test_extract_needs_a_path_not_inline_content():
    ok = {"source_id": "s", "content_path": "x.md", "concept_index": []}
    assert _hooklib.missing_fields("extract", ok) == []
    inline = {"source_id": "s", "content": "text", "concept_index": []}
    assert "content_path" in _hooklib.missing_fields("extract", inline)


def test_config_values_are_required_never_defaulted():
    assert "fetch_method_recheck_days" in _hooklib.missing_fields("discover", {})


@pytest.mark.parametrize("verdict,missing", [
    ({"status": "new", "trust_score": 90}, []),
    ({"status": "supersession", "replaces": "f1", "trust_score": 90}, []),
    ({"status": "duplicate_corroborating", "matches": "f1", "new_source": "s2",
      "trust_score": 50, "independent": True}, []),
    ({"status": "duplicate_corroborating", "matches": "f1"},
     ["independent", "new_source", "trust_score"]),
])
def test_verdict_shapes(verdict, missing):
    assert _hooklib.missing_fields("merge", verdict) == missing


def test_duplicate_exact_must_never_reach_publish():
    """Merge stops on duplicate_exact; one arriving here is a Merge bug."""
    result = _hooklib.missing_fields(
        "publish", {"verdict_status": "duplicate_exact", "changed_fields": []})
    assert result and "verdict_status" in result[0]


# --------------------------------------------------------------------------
# Mode calls are not verdicts
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stage,mode", [("publish", "resolve_links"),
                                        ("merge", "resume_check")])
def test_mode_calls_carry_no_verdict(stage, mode):
    assert _hooklib.missing_fields(stage, {"mode": mode}) == []


def test_modes_are_per_stage_not_a_global_exemption():
    assert _hooklib.missing_fields("merge", {"mode": "resolve_links"}) != []
    assert _hooklib.missing_fields("publish", {"mode": "nonsense"}) != []


# --------------------------------------------------------------------------
# Value formats: trust score and timestamps
# --------------------------------------------------------------------------

@pytest.mark.parametrize("score,valid", [
    (92, True), (0, True), (100, True),
    (0.9, False),      # the 0-1 float a stage produced when it guessed the scale
    (150, False), (-1, False), (True, False),
])
def test_trust_score_is_an_integer_0_to_100(score, valid):
    payload = {"status": "new", "trust_score": score}
    assert (_hooklib.missing_fields("merge", payload) == []) is valid


@pytest.mark.parametrize("ts,valid", [
    ("2026-09-06T16:07:41Z", True),
    ("2026-09-06", False),          # bare date: same-day runs are unorderable
    ("2026-09-06 16:07:41", False),
    (None, True),                   # absent is fine
])
def test_last_confirmed_must_be_a_full_timestamp(ts, valid):
    payload = {"status": "new", "trust_score": 90, "last_confirmed": ts}
    assert (_hooklib.missing_fields("merge", payload) == []) is valid


def test_per_fact_timestamps_are_checked_too():
    payload = {"status": "new", "trust_score": 90,
               "facts": [{"last_confirmed": "2026-09-06T16:07:41Z"},
                         {"last_confirmed": "2026-09-06"}]}
    problems = _hooklib.missing_fields("merge", payload)
    assert problems and "facts[1]" in problems[0]


# --------------------------------------------------------------------------
# End-to-end hook behaviour
# --------------------------------------------------------------------------

def test_only_publish_writes_to_knowledge():
    doc = {"file_path": "knowledge/concepts/min-bid.md"}
    assert fire("validate_before_write.py",
                {"cwd": ".", "agent_type": "publish", "tool_input": doc})[0] == ALLOW
    for caller in ("merge", "discover", None):
        event = {"cwd": ".", "tool_input": doc}
        if caller:
            event["agent_type"] = caller
        assert fire("validate_before_write.py", event)[0] == BLOCK


def test_source_registry_is_exempt_from_the_write_gate():
    """Discover maintains it every run; it sits under knowledge/ but is not OKF."""
    code, _ = fire("validate_before_write.py",
                   {"cwd": ".", "agent_type": "discover",
                    "tool_input": {"file_path": "knowledge/.sources.json"}})
    assert code == ALLOW


def test_orchestrator_writes_only_logs_and_runs_only_a_clock():
    def orch(tool, inp):
        return fire("orchestrator_write_scope.py",
                    {"cwd": ".", "agent_type": "orchestrator",
                     "tool_name": tool, "tool_input": inp})[0]

    assert orch("Write", {"file_path": "logs/run_x.jsonl"}) == ALLOW
    assert orch("Write", {"file_path": "knowledge/concepts/x.md"}) == BLOCK
    assert orch("Bash", {"command": "date -u +%Y-%m-%dT%H:%M:%SZ"}) == ALLOW
    assert orch("Bash", {"command": "rm -rf knowledge/"}) == BLOCK


def test_validate_may_only_escalate_to_discover():
    def task(target):
        return fire("task_scope.py",
                    {"agent_type": "validate",
                     "tool_input": {"subagent_type": target}})[0]

    assert task("discover") == ALLOW
    assert task("merge") == BLOCK and task("publish") == BLOCK


def test_hooks_fail_open_on_unparseable_input():
    """A broken hook must never wedge the pipeline."""
    for hook in ("schema_validation.py", "validate_before_write.py",
                 "orchestrator_write_scope.py", "task_scope.py"):
        proc = subprocess.run([sys.executable, str(HOOKS / hook)],
                              input="not json at all",
                              capture_output=True, text=True, cwd=str(ROOT))
        assert proc.returncode == ALLOW, hook
