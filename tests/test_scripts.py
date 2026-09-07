"""Tests for the deterministic half of the system.

These cover scripts/ rather than the agents, deliberately: the agents are
prompts whose behaviour is judgment, but everything in scripts/ has exactly one
right answer and is therefore testable in isolation. That split is the whole
architecture, so it is also the test strategy.

    python -m pytest tests/ -q
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import clean_content  # noqa: E402
import hash_compare  # noqa: E402
import trust_lookup  # noqa: E402


# --------------------------------------------------------------------------
# clean_content - output feeds the content hash, so stability is the contract
# --------------------------------------------------------------------------

PAGE = """<html><head><title>T</title><style>body{color:red}</style></head>
<body><nav class="navbar"><a href="/">Home</a></nav>
<div class="cookie-consent">We use cookies</div>
<main><h1>Minimum bid</h1><p>The minimum bid is <b>$0.02</b>.</p>
<ul><li>US</li><li>UK</li></ul></main>
<footer>(c) Amazon</footer></body></html>"""


def test_strips_chrome_keeps_content():
    out = clean_content.clean_html(PAGE)
    assert "Minimum bid" in out and "$0.02" in out
    for chrome in ("Home", "cookie", "color:red", "(c) Amazon", "T\n"):
        assert chrome not in out, "chrome leaked: {!r}".format(chrome)


def test_output_is_deterministic():
    """Same bytes in, same bytes out - the re-run guarantee depends on it."""
    assert clean_content.clean_html(PAGE) == clean_content.clean_html(PAGE)


def test_normalize_is_idempotent():
    once = clean_content.normalize(PAGE)
    assert clean_content.normalize(once) == once


def test_markdown_structure_survives():
    out = clean_content.clean_html(PAGE)
    assert "# Minimum bid" in out
    assert "- US" in out and "- UK" in out


# --------------------------------------------------------------------------
# hash_compare - change detection and registry bookkeeping
# --------------------------------------------------------------------------

def test_known_sha256():
    assert hash_compare.sha256_text("hello world").startswith("b94d27b9934d3e08")


def test_registry_roundtrip_and_status(tmp_path):
    reg = tmp_path / "sources.json"

    def run(*args):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "hash_compare.py"),
             "--registry", str(reg), *args],
            capture_output=True, text=True, input="content v1")
        return json.loads(proc.stdout)

    assert run("compare", "s1", "-", "--update")["status"] == "new"
    assert run("compare", "s1", "-")["status"] == "unchanged"

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hash_compare.py"),
         "--registry", str(reg), "compare", "s1", "-"],
        capture_output=True, text=True, input="content v2")
    assert json.loads(proc.stdout)["status"] == "changed"


def test_failure_and_success_signals_are_distinct(tmp_path):
    """A fetch failure counts. A JS-rendering flip must not."""
    reg = tmp_path / "sources.json"
    script = str(ROOT / "scripts" / "hash_compare.py")

    def call(*args, stdin=""):
        return json.loads(subprocess.run(
            [sys.executable, script, "--registry", str(reg), *args],
            capture_output=True, text=True, input=stdin).stdout)

    assert call("fail", "s1")["consecutive_failures"] == 1
    assert call("fail", "s1")["consecutive_failures"] == 2

    # Recording a JS-rendered fetch method is not a failure.
    call("method", "s1", "js_rendered")
    assert call("get", "s1")["consecutive_failures"] == 2

    # A successful capture resets the counter.
    call("compare", "s1", "-", "--update", stdin="ok")
    assert call("get", "s1")["consecutive_failures"] == 0


# --------------------------------------------------------------------------
# trust_lookup - baselines come from the list, never from reasoning
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url,band,official", [
    ("https://advertising.amazon.com/API/docs/en-us/", "official", True),
    ("https://developer.amazon.com/docs/ads", "official", True),
    ("https://github.com/amzn/ads-advanced-tools-docs", "official", True),
    ("https://raw.githubusercontent.com/amzn/x/main/README.md", "official", True),
    ("https://ppc.sellercentral.com/guide", "known_unofficial", True),
    ("https://some-random-blog.example/post", "unlisted", False),
])
def test_bands(url, band, official):
    r = trust_lookup.lookup(url)
    assert r["band"] == band and r["official"] is official


def test_path_scoping_respects_segment_boundary():
    """github.com/amzn must not confer trust on github.com/amzn-lookalike."""
    assert trust_lookup.lookup("https://github.com/amzn/repo")["band"] == "official"
    for other in ("https://github.com/amzn-lookalike/repo",
                  "https://github.com/someoneelse/repo"):
        r = trust_lookup.lookup(other)
        assert r["band"] == "unlisted" and r["flag_for_review"] is True


def test_unlisted_is_flagged_not_rejected():
    r = trust_lookup.lookup("https://unknown.example/x")
    assert r["flag_for_review"] is True
    assert 10 <= r["baseline"] <= 20, "unlisted is scored low, not zero"


def test_every_listed_score_sits_inside_its_band():
    for domain, (band, score, _) in trust_lookup.TRUSTED_DOMAINS.items():
        lo, hi = trust_lookup.BANDS[band]["min"], trust_lookup.BANDS[band]["max"]
        assert lo <= score <= hi, "{} scores {} outside {}".format(domain, score, band)


def test_clamp_keeps_adjusted_scores_in_range():
    assert trust_lookup.clamp(105) == 100 and trust_lookup.clamp(-5) == 0
