# PicotooPet 2.3.23.1 — RED Contract Evidence

RED head: `7941ec607fa5d894e41ac92b3c2d2e90b75646a7`
Base: frozen 2.3.22.1 head `f018aa538253b12a72dca859981c37c8bd7bd685`

## Expected RED

This commit intentionally contains failing regression contracts before production implementation.

- Python schema test requires Migration 16 and six new quality-evaluation tables; production still stops at schema 15.
- Python evaluation test requires `picotoopet_core.deep_ai.evaluation`; that module does not yet exist.
- API test requires authenticated evaluation snapshot/run/metric/candidate/review routes; those routes do not yet exist.
- Windows client smoke references 2.3.23.1 evaluation contracts and client methods; production types do not yet exist.
- Windows real STA WPF smoke references `QualityEvaluationPanelViewModel` and `QualityEvaluationPanel`; production UI does not yet exist.

## Frozen behavior under test

`Quality Learning Facts → Evaluation Snapshot → Offline Evaluation → Improvement Candidate → candidate_ready`

The RED tests also freeze these safety rules:

- no prompt/model/provider/endpoint/API-key/budget/formula/SQL injection;
- explicit metric numerator/denominator and missing-data semantics;
- cohorts below five human decisions cannot trigger candidates;
- five deterministic candidate classes only;
- `AcceptedForShadow` is a durable review fact and performs zero runtime mutation;
- terminal 2.3.22.1 Deep-AI history is read-only evaluation evidence and cannot be reopened;
- Windows record bindings are explicit OneWay and the panel exposes no free execution configuration.

The next implementation step is GREEN. This RED document is evidence only; it does not authorize merge, tag, release, real paid execution, or policy promotion.
