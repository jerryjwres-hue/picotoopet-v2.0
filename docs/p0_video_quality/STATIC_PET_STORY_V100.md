# P0 #233 — static-pet-story-v1.0.0: pure semantic feasibility contract

This test-only Core policy recognizes **temporal story payoff**, not a lasting change
of eye, body or scene state. It has no API router, production activation, Goal mutation,
model call, GPU authority or alteration to legacy `STORY_NO_CHANGE`.

## Required business behavior

For an explicitly authorized NEW pet-only v2 Goal, the canonical three-shot 12-second
composition has three exact Core events in order:

1. Shot 1 — `BLINK_AND_REOPEN` (one blink, both eyes reopen, no head/body reposition).
2. Shot 2 — `SUBTLE_BREATHING` (fixed pose, fixed subject and scene).
3. Shot 3 — `SUBTLE_BREATHING` (same identity and scene, no invented end-state).

Each shot is four seconds and uses an allowed **STATIC** framing, with adjacent shots
using different authorized framings. The event sequence and visible framing progression
constitute a plan-level temporal arc; this is not proof that Comfy frames show the beat.

## Authority and semantic gate boundaries

The evaluator consumes:
- `StateFactsV1` (owner-approved identity, pose, scene, allowed events),
- `StateSpineV1` (Core deterministic states/shot events),
- `UnlockedVideoBibleProposalV1` (unlocked model proposals only),
- `CreativeScriptResult` (three matching 4-second beats),
- a versioned `StaticPetStoryOptInV1` whose Goal, subject, objective/source/facts digests
  match exactly **and** a trusted Core callback that verifies its immutable reviewed policy
  commitment in the existing canonical ledger.

A request body saying `owner_approved=true` or supplying a guessed commitment ID is
**not** an authorization. The evaluator has no ledger access; a production integration
MUST implement the trusted callback with real signed/actor-scoped Core evidence lookup
and prove it in tests before enabling the policy. Without this callback it returns
`STATIC_STORY_OWNER_REVIEW_UNVERIFIED`.

The evaluator regenerates a canonical State Spine and compares **typed fields and digest**;
string differences like `state_ref=S0` versus `state_ref=S3` alone never count as story
change. Missing blink, unauthorized events, camera progression failure, altered eye
states, changed pose/head/identity/scene/camera, bad source digest, legacy/non-opt-in
contracts or model-declared human review all reject.

## Release gating

This is a **pure isolated candidate**, deliberately not wired into
`creative/quality.py`, `video_bible.py`, Worker, Production Compiler or Core API.
Do not use a test synthetic callback as production proof.

**Still blocked:** trusted opt-in stored in Owner Structured Review, Windows review UI,
verified Windows↔Mac encrypted owner-review transport and an integrated source/reference
acceptance test. Only after those gates can this opt-in change the selected static pet-only
terminal-state semantic criterion. It must not weaken old non-static Story Gate checks.

Real Maotai visual identity/pose and video acceptance require verified actual reference
bytes, approved rights, and human frame review. Core semantic PASS alone is not a real
accepted video. GPU remains HOLD.
