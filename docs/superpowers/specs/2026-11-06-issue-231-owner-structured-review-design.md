# Issue #231-B Owner Structured Review Design

## Intent

Add a Core-only, authenticated Proposal → Preview → Atomic Commit flow that turns explicit
owner decisions into immutable `state_facts.v1`. This is the trusted source ingress required by
the State Spine work in PR #230. It must use the scoped `OwnerPrincipal` from PR #234 and the
existing `canonical_evidence` ledger without changing production consumers.

## Goals and non-goals

- Proposal reads the current Goal, its persisted Creative source snapshot, objective digest and
  subject-scoped canonical evidence. It accepts no caller evidence list.
- Preview applies one decision per owner-facing field: `CONFIRM`, `CORRECT`, or `UNKNOWN`.
  It performs no writes and returns either a strict `StateFactsV1` candidate or `NEEDS_HUMAN`.
- Commit replays Preview, checks actor, Goal, subject, source revision and all digests, then writes
  correction evidence plus the immutable facts record in one SQLite transaction.
- Exact Idempotency-Key replay returns the original result; changed content, stale sources or
  conflicting keys return HTTP 409.
- Existing owner evidence, legacy APIs, historical jobs and all production consumers remain
  unchanged and opt-in.
- No model, Goal, Worker, GPU, Story Gate, Windows UI, deployment or real credential changes.

## Chosen approach

Use a dedicated versioned review service and router. The service imports `OwnerPrincipal` and
`StateFactsV1`, resolves all authority from persisted Core facts, and stores review artifacts in
the existing canonical ledger. A small transaction-aware batch method is added to that ledger;
no table or migration is added.

Alternatives rejected:

- Extending the old free-text owner packet would preserve its caller-supplied evidence surface
  and cannot express field-level decisions safely.
- Adding a new review table would duplicate the canonical ledger and violate Issue #231.
- Persisting Preview would make the preview endpoint side-effecting and create stale partial
  approvals.

## API

- `GET /api/v1/owner-structured-reviews/goals/{goal_id}/proposal`
- `POST /api/v1/owner-structured-reviews/preview`
- `POST /api/v1/owner-structured-reviews/commit` with `Idempotency-Key`

All three routes use `require_owner_principal`, which enforces direct loopback transport and a
separate owner-review credential. Subject and actor authorization are Core-derived.

Proposal exposes evidence metadata only: IDs, types, trust, hashes, authority and whether photo
bytes were verified. Free text and media never leave the service. A typed value is eligible for
`CONFIRM` only when a canonical evidence record explicitly stores that exact field path/value and
its persisted authority/trust is compatible. Vague legacy statements remain `UNKNOWN`.

Preview covers these owner-facing paths:

- `subject_lock.{subject_id,species,breed_or_type,coat_or_appearance,distinguishing_marks}`
- `pose_lock.{body_pose,head_direction,support_surface}`
- `scene_lock.{environment,lighting,temporary_accessories}`
- `camera_lock.allowed_framings`
- `allowed_events`

Core deterministically derives lock IDs, `pose_lock.fixed=true`, and
`camera_lock.movement=STATIC`. Identity corrections are `OWNER_ATTESTATION`/Trust D. Pose,
scene, camera and event corrections are `OWNER_CREATIVE_INTENT`/Trust E. An existing approved
reference may only be confirmed when its persisted record says so; callers cannot select an
authority class.

## Digests and freshness

`source_revision_digest` binds the Goal row, Creative job/source snapshot and all current
subject evidence identities/hashes. `proposal_digest` additionally binds the authenticated actor
and registry revision. `review_digest` binds the canonical decisions. `preview_digest` binds the
review digest and generated `StateFactsV1` candidate. Commit recomputes every digest and checks
the source revision again while holding `BEGIN IMMEDIATE`.

The Idempotency-Key is hashed into a canonical ledger origin ref. The final commit evidence stores
the request fingerprint and response. Equal replay returns that response before freshness checks;
different content with the same key conflicts. A later key against a now-stale preview conflicts.

## Failure behavior

- 401: missing or invalid owner-review credential.
- 403: device token, transport, subject scope or actor mismatch.
- 404: Goal or its Creative source snapshot does not exist.
- 409: stale source/proposal/preview, evidence conflict, idempotency mutation or transaction
  conflict.
- 422: malformed/duplicate/poisoned structured input.
- `NEEDS_HUMAN`: missing or `UNKNOWN` decisions, untrusted CONFIRM, or invalid state contract;
  no model call is possible from this service.

## Verification

Tests use only synthetic SQLite data and loopback TestClient calls. They cover deterministic
digests, free-text non-promotion, actor/subject scope, 401/403/409, all evidence binding checks,
preview no-write, idempotence, stale sources, rollback, preservation of pre-existing evidence and
the frozen OpenAPI examples. Full Core/Worker native CI must run on the final exact SHA.
