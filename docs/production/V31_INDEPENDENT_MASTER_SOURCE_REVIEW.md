# V3.1 independent MASTER evidence review (CPU-only, held)

## What changes

An independent human reviewer credential may now record a review of the **real Core-frozen Episode**, the immutable Owner Plan SHA, the exact source-bindings SHA and each source/evidence object's actual current bytes.

- New existing-registry permission: `master.verify`. It is **not** implied by `storypack.review`, `asset_use.attest`, or the paired device token.
- A reviewer must have an explicitly provisioned credential on the exact `pet:...` subject and a different `actor_id` from the frozen Owner. Only direct Mac loopback access is accepted.
- Existing endpoints are unchanged; separate `POST /api/v1/studio/storypacks/master-review/{commit,verify,revoke}` use the existing audit ledger.
- The reviewed source set must match **all** Owner-claimed StoryPack assets, not just first-frame files. Core re-reads its frozen Episode, the real `gen.keyframe` Task manifests, the current storyboard/asset-use audit decisions, and every managed source/evidence byte.
- The separate reviewer provides exact source/ref hashes and explicitly confirms that a **human** checked provenance and commercial-AI use. `self_created` accepts the exact original image as the evidence object; commercial licence or written permission requires the separate evidence artifact already recorded in Core and bound to the Owner claim's evidence digest. A self-created image alone does not legally prove ownership.
- Same exact review is idempotent; changed plan, changed evidence, missing source, expired/revoked Owner statement, different reviewer, or revoked master review is rejected. Revocation is an append-only audit event.

## Deliberate boundary

This records a **distinct human provenance review**, not automatic legal certification. The software cannot independently judge the semantics of a licence document or prove who took a photo. Its reviewer must inspect those materials; a different `actor_id` is a technical separation only and cannot prove two real-world people are different.

Every receipt returns `gpu_authorized=false`, `can_lease=false`, and `can_generate=false`. Existing Owner-mode `POST /executors/lease` remains 204. This change does **not** issue GPU permissions, Worker local Plan attestation, dynamic-story policy admission, a new scheduler, or a new queue.

## Remaining P0 chain

The next scoped step is to join this persisted review ID and its current revocation state to the **same** frozen Plan and **specific** Windows worker-local SHA receipt, before creating a narrowly scoped, revocable GPU admission for one Production Job. Release must be inside existing Core lease/Worker gates, not an unrelated HTTP toggle. A genuine local three-shot render, SHA receipts, QC and human visual acceptance remain UNVERIFIED.

No private user assets, machine access, or GPU tasks are used in CI: synthetic, owned source fixtures only.
