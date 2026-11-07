# Owner Structured Review v1

This Core-only API creates immutable `state_facts.v1` from an authenticated owner's explicit
field decisions. It is disabled unless the separate owner-review registry from PR #234 is locally
provisioned. Current remote/LAN use is forbidden; the dependency accepts direct loopback only.

## Flow

1. `GET /api/v1/owner-structured-reviews/goals/{goal_id}/proposal`
2. `POST /api/v1/owner-structured-reviews/preview`
3. After the user approves the exact preview, `POST /api/v1/owner-structured-reviews/commit`
   with an `Idempotency-Key` header.

Proposal never accepts evidence IDs from the caller and never returns evidence text or media.
Legacy free text remains `UNKNOWN` unless a prior committed structured review contains the exact
field/value binding.

## Explicit static story opt-in (default OFF)

The optional `story_policy_opt_in` field on Preview request is either `null` (default)
or `"static-pet-story-v1.0.0"`. The latter is an **explicit owner choice** to request
source-bound static pet story semantics, NOT authority to start the Creative/Comfy/GPU path.
Having `BLINK_AND_REOPEN` in `allowed_events` alone must NOT auto-select the policy.

Core checks that the confirmed facts allow both blink-and-reopen and subtle breathing and
at least two static camera framings before returning READY with that selected policy.
The choice is included in the Core-calculated review/preview digests, canonical immutable
Commit value and Commit response. Omitted or null retains the old general Story Gate.
A mismatch, changed selection or altered idempotent replay receives a conflict, not silent
upgrade. This is a *selection and audit contract only*; actual Story Gate adaptation and
rendered-video acceptance remain separate and inactive.

## Field decisions

Every owner-facing field is one of:

- `CONFIRM`: reuse the proposal's persisted, approved typed evidence.
- `CORRECT`: make the supplied typed value a new owner-reviewed canonical fact at Commit.
- `UNKNOWN`: keep the review in `NEEDS_HUMAN`; no model call occurs.

Identity corrections are owner attestations. Pose, scene, camera and allowed-event corrections
are creative intent and do not become observed photo facts. `photo_bytes_verified=false` remains
unchanged unless the separate reference approval workflow verifies actual bytes.

Example decision:

```json
{
  "field_path": "subject_lock.species",
  "decision": "CORRECT",
  "corrected_value": "cat"
}
```

Commit repeats the Preview request plus the exact `source_revision_digest`, `review_digest` and
`preview_digest`. Core recomputes all values while holding one SQLite transaction. Exact replay
returns the original commitment; changed content, stale evidence or digest mismatch returns 409.

The complete machine-readable schema and examples are frozen in
`contracts/openapi/mac_core_v1.openapi.json`.
