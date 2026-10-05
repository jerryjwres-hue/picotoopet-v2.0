# Goal Video Return Bridge Design

## Intent

Close the existing `product.research_to_video` / `video.creative` continuation after a user manually runs the verified Web GPT handoff. Mac Core accepts one bounded typed return, proves that it belongs to the completed Goal handoff, adopts it through the existing Creative quality and package path, and creates or reuses the existing `production.comfyui.v1` Production Job.

## Frozen boundaries

- Mac Core remains the fact source; Web GPT upload and return submission remain manual.
- The return cannot select a provider, model, endpoint, renderer, workflow, node, path, command, or executable.
- Claimed verified fact IDs must be a subset of the evidence IDs in the exact verified handoff ZIP. Inference and creative text remain separately labelled and never become verified facts.
- Creative adoption must pass the existing strict stage schemas, `CreativeQualityGate`, immutable `CreativeArtifactStore`, and `CreativeRepository` package identity checks.
- Production is created only through `ProductionService.create_job()` and its existing closed compiler.
- Research Gateway remains read-only; Windows remains the GPU executor; no Maotai/release gate changes are in scope.

## Contract and validation

`GoalVideoReturnV1` is a strict, bounded Pydantic contract with `extra="forbid"`. It binds `schema_version`, `goal_id`, `handoff_sha256`, `prompt_version`, and `generated_at`; keeps `verified_fact_ids`, `inference_summary`, and `creative_summary` separate; and embeds the four existing Creative stage result types (`IdeaRankingResult`, `CreativeBriefResult`, `CreativeScriptResult`, `ShotPlanResult`).

`GoalHandoffAccess` gains a verified context read that reuses the existing Goal → Workflow → Result checks, re-verifies the managed ZIP, and reads only the bounded `HANDOFF_MANIFEST.json`. The return validator rejects a wrong Goal, unsupported Goal intent, incomplete handoff, digest/version mismatch, unknown evidence IDs, duplicate fact IDs, and existing Creative forbidden-authority markers.

## Creative adoption

The handoff evidence list is deterministically projected into a `NormalizedCreativeSourceSet`: one synthetic immutable source package identity and one stable finding reference per original evidence ID. The source-set digest also includes the return digest, so the same handoff cannot accept a conflicting creative return.

`CreativeIntelligenceService` gains a bounded external-adoption method. It creates/reuses a Creative Job, runs every supplied stage through `CreativeQualityGate` in order, persists immutable PASS stage records, and delegates finalization to a shared Creative package finalizer. The existing Worker coordinator is refactored to use that same finalizer; there is no second package builder or raw Goal-side repository/store write.

The resulting manifest keeps the normal Creative Package v1 shape and adds fixed Core-owned provenance for the Goal ID, handoff digest, prompt version, return digest/object hash, and verified evidence IDs. It does not claim a provider/model identity supplied by the caller.

## Persistence and replay

No migration or duplicate lifecycle table is added. The canonical return JSON is written to the existing content-addressed `ResultStore`. Existing `artifact_provenance` records the verified handoff artifact and a deterministic `goal-video-return:<goal_id>` artifact whose SHA-256 is the canonical return digest and whose metadata stores the Creative Job/Package and Production Job identities.

Creative and Production idempotency keys are deterministic per Goal + handoff. An identical replay reuses all identities. A changed return conflicts through the Creative source-set/idempotency binding even if a crash happened before the final artifact link; after the link exists its immutable SHA binding rejects the conflict. A restart reconstructs status from artifact metadata and the existing Creative/Production repositories.

## API and errors

Authenticated `POST /api/v1/autonomous/goals/{goal_id}/handoff/return` accepts `GoalVideoReturnV1`; authenticated `GET` on the same path returns the durable linkage/status projection. Schema errors are `422`; missing Goals are `404`; stale handoffs, provenance failures, conflicting replay, or incomplete linkage are bounded `409` errors with no untrusted payload echoed.

## Test strategy

TDD covers valid return → canonical Creative Package → existing Production Job; unknown evidence; wrong/stale digest or prompt version; extra provider/renderer authority; identical replay; conflicting replay including the pre-link crash identity; and restart reconstruction. Existing autonomous Goal/handoff, Creative quality/package, Production compiler/repository, security, and release-goal contract suites remain in the regression gate.
