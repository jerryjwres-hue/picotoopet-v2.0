# S001 — Ollama loopback connection lifecycle

## Goal

Reduce unnecessary localhost TCP churn to Ollama without changing product behavior.

Observed on real Mac:
- ~16.5k TCP TIME_WAIT
- ~10.2k loopback TIME_WAIT pointed at Ollama :11434
- health-supervisor cadence itself was ~60s, not a tight loop

Known code fact:
`picotoopet-core supervise --loop` currently calls `_run_health()` every cycle.
`_run_health()` rebuilds and closes the full `Services` container every cycle, including a fresh `OllamaClient/httpx.Client`.

## Branch

Work only on:
`fix/ollama-loopback-connection-lifecycle`

Base:
`feature/autonomous-intelligence-e2e-goal-center-2.3.27.1` @ `e7421768caf3cd1f9fbb99aee4dab2ea585fe3cd`

## Required implementation

1. Make `supervise --loop` reuse long-lived health dependencies across ticks:
   - build Services once per supervisor process
   - reuse one `HealthSupervisor`
   - reuse the same `OllamaClient/httpx.Client` connection pool
   - close Services exactly once on exit/error
   - preserve current one-shot `health` behavior

2. Preserve cadence:
   - exactly one health check per configured interval
   - no busy loop
   - no background extra probe loop

3. Audit the Mac Worker paths that hit Ollama/localhost:
   - `OpenAiCompatibleLocalIntelligenceAdapter.health()`
   - adaptive model budget observer
   - isolated model runner / local intelligence
   - resident manager
   Only change additional paths if there is concrete evidence of per-poll/per-task client recreation or missing close.
   Do not speculate and do not broaden the task.

4. Do NOT solve this by:
   - expanding macOS ephemeral port range
   - changing TCP kernel settings
   - reducing TIME_WAIT system-wide
   - disabling health checks
   - weakening Ollama readiness
   - changing model/provider semantics

## Expected files

Primary:
- `src/picotoopet_core/cli.py`
- focused tests for supervisor lifecycle

Only if evidence requires:
- `src/picotoopet_core/ollama/client.py`
- `src/picotoopet_core/business/local_intelligence.py`
- `src/picotoopet_core/ollama/model_runner.py`
- their focused tests

Do not touch:
- Windows
- Goal Center / C001 / C002
- Creative / Production contracts
- database schema
- deploy/macos installer or rollback
- Natural Motion assets

## Tests required

Add deterministic tests proving:
- loop supervisor builds Services once across multiple ticks
- the same resident/Ollama client is reused
- health `run_once()` occurs once per tick
- configured sleep cadence remains
- Services closes exactly once when supervisor exits/raises
- one-shot `health` still creates/closes its own Services once
- no extra model download/load behavior is introduced

If another localhost/Ollama client leak is found, add a focused regression test proving the leak before fixing it.

## Acceptance

PASS when:
- focused tests pass
- full relevant Python regression passes
- Ruff passes
- no architecture/security boundary changes
- diff contains only evidence-backed lifecycle fixes
- report includes:
  - root cause(s) proven
  - files changed
  - tests run
  - residual risk

## Stop conditions

Do not merge, tag, release, or modify the base branch.
Do not change macOS kernel/network settings.
If no additional leak beyond supervisor recreation can be proven, stop there and report that explicitly.
