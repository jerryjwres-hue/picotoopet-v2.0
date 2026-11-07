# Issue #229 State Spine v1.1.0 Design

## Scope

This change starts from PR #227 at
`1d81b62338a54f53d37c8d41027dd8b2fee049b1`. It adds a pure, Core-owned
`state_facts.v1` contract and deterministic State Spine for new pet-only v2 jobs. It does not
activate a new production stage, persist new records, alter an old job, or change the legacy
`video_bible.v1`, `shot_plan.v1`, quality gate, or Production Compiler contracts.

The stopped PR #228 prompt experiment is regression evidence only.

## Approved boundaries

- Canonical payloads use sorted compact UTF-8 JSON. SHA256 fields exclude their own digest.
- Identity, pose, scene, and camera facts are Core-owned locks. Identity taxonomy needs
  owner-confirmed structured evidence and cannot be promoted from creative intent.
- The model may propose only an event, visible action wording, and an allowed framing. Attempts
  to submit locked fields fail strict validation; conflicts fail binding and are never silently
  overwritten.
- S0 through S3 are typed objects. A shot's closing state ID is the next shot's opening state ID.
- `BLINK_AND_REOPEN` and `SUBTLE_BREATHING` are reversible micro-events. They do not by
  themselves authorize an invented terminal state change.
- Final shot fields keep the existing Video Bible schema. The compiled prompt projection must
  contain the complete identity, pose, scene, and camera locks; state strings carry compact state
  and lock references instead of repeating pose prose.

## Owner approval boundary

The existing authenticated owner evidence flow accepts free-text identity, scene, and creative
intent claims. It does not capture typed taxonomy, pose, scene, camera, per-field evidence
bindings, or a reviewed canonical `state_facts.v1` digest. Therefore this branch implements and
tests the pure contract and binder but does not add a persistence/API shortcut or activate it in
production.

Activation requires a minimal authenticated review contract which:

1. derives a prefilled typed proposal from existing evidence;
2. lets the owner confirm or correct every locked field;
3. records per-field evidence IDs and authority kind;
4. previews the canonical digest before confirmation; and
5. stores the signed/approved digest through the existing evidence or approval mechanism.

## STOP semantics

- Missing or inadequate evidence returns `NEEDS_HUMAN` before any model call.
- An identity taxonomy binding backed only by creative intent is rejected.
- A model proposal containing a locked field, changing the expected event, or requesting an
  unapproved framing is rejected.
- If the objective permits only blink-and-reopen followed by subtle breathing while the current
  Story Gate demands a terminal state change, return the explicit
  `STATE_SPINE_STORY_NO_CHANGE_CONFLICT`. Do not invent half-closed eyes or relax the gate.

