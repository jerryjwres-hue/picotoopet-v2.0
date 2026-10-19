# P0-F: C009C smoke compatibility with the frozen C011 QA gate (tests only)

Scope: `windows/desktop/tests/PicotooPet.PostProductionDelivery.SmokeTests/CoordinatorIntegrationTests.cs` only. No production file, no QA implementation and no other test project changed.

## Evidence

| Step | Commit | Native Windows run | Result |
| --- | --- | --- | --- |
| RED, frozen C012 | `b1977ffc36d9151e1b8ff17d369583d0ed0e0334` | [39341133604](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39341133604) | FAIL: `C009C unexpected failure in FallbackReady` (`ModeAsync`, first fixture) |
| Repair, first push | `1d5b511bc1ddf22d459a91e751e1676ee5c8ec9f` | [39341373081](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39341373081) | FAIL at Release build: analyzer CA1869 (new `JsonSerializerOptions` per call) |
| Repair, analyzer fix | `855cee601fd3c373239a9fee7ffde6493722e760` | [39341664331](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39341664331) | PASS: pinned SDK, Release build, `POSTPRODUCTION_DELIVERY_ISOLATED_SMOKE=PASS` |

## Root cause

`PostProductionDeliveryCoordinator.ReconcileAsync` requires the injected C011 authority and QA verifier and throws `C011_QA_GATE_UNAVAILABLE` otherwise (`PostProductionDeliveryCoordinator.cs`, the check after the candidate is built). The legacy C009C fixture constructed the coordinator without them and expected `FallbackReady`/`MasteredReady` as final states. That is stale test harness, not a production defect.

## What the harness does now

- Injects a test-scoped, fail-closed Core authority and QA verifier. The verifier re-hashes the selected managed file, checks lineage against the authority input, and issues a receipt whose digest follows the same canonical rule as the production receipt (snake_case JSON, without `receipt_digest` and `verified_at`). If the production receipt digest rule changes, this harness fails closed.
- Ready is `DeliveryReady` only after QA; Open requires the exact receipt.
- Preserved: required-master failure never falls back to C004, restart from durable files, goal switch, dispose during reconciliation, click-time tamper rejection.
- New regressions: no QA authority gives Failed with `CanOpen=false`; a QA denial never reaches Ready; a changed Core authority, a swapped receipt and tampered bytes are each rejected at Open; an untouched approved candidate opens exactly once.

## Not claimed

The verifier is a synthetic stand-in: no real decode, no FFmpeg, no GPU. `FinalVideoQaException` (`QaFailed`) and the real `FinalVideoQaService` are internal to the Desktop assembly and stay covered by the C011/C010A native suites. Full P0 cross-branch integration and any live GPU run are UNVERIFIED.
