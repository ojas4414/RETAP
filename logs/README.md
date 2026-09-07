# Run logs

One JSON Lines file per run, written by the orchestrator. Kept as evidence of
how the pipeline behaves on real sources, not as exhaustive history — runs that
were cut short by session limits or killed mid-flight have been pruned, since
they record operator mistakes rather than system behaviour.

| Log | What it shows |
|---|---|
| `run_20260906T160258Z.jsonl` | A complete run, `run_start` through `link_resolution` and `run_end`. The fetch-method flip from `static` to `js_rendered` after the usable-content check failed, and 24 events of stage sequencing. |
| `run_20260907T062631Z.jsonl` | **Skip-if-unchanged on live data**: one source reported `unchanged` on a matching hash and was skipped without a fetch, while others were processed. Also records two sources yielding zero facts — one a short README, one a JS-rendered page that served an error shell to a plain fetch. |
| `run_20260907T063752Z.jsonl` | Parallel per-fact Validate: 13 facts dispatched concurrently and returned in ~90 seconds, with `trust_score` baselines drawn from `scripts/trust_lookup.py` (band `official`, baseline 92, finals 88-92). |
| `run_20260907T113700Z.jsonl` | The run that produced the current bundle in `knowledge/concepts/`. **Its log is incomplete**: it stops at 11:44 while the published documents carry timestamps to 12:05, so Validate, Merge and Publish went unrecorded. The orchestrator's incremental-logging rule was not followed here. Kept honestly rather than presented as a full trace — see DESIGN.md on the run log being the least reliable part of the system. |
