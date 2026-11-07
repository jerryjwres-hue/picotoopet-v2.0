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
