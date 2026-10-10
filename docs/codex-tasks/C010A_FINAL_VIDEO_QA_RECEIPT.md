# C010A — Windows Deterministic Final Video QA & Immutable PASS Receipt

## Branch and base

Branch: `feature/final-video-qa-receipt-core-v1`

Starting point: `3150702b022a6e3432e148ccff2e2ab12963bb15` (C009B pending CI).

Read first:
- `docs/architecture/video/C010A_IMPLEMENTATION_BRIEF_V1.md` (copied verbatim from reviewed GPT architecture window)
- `docs/architecture/video/G006_FINAL_VIDEO_QA_RECEIPT_V1.md` if available in your checkout; otherwise use the brief and actual product contracts
- actual C004/C005/C007/C008/C009A/C009B code. Do not guess types.

## Goal

Implement C010A only: deterministic Windows read-only validation of the exact final-video candidate and an immutable PASS-only receipt catalog. No Goal Center/UI changes.

Final candidate:
- `NarrationRequired || OverlaysRequired` => exact verified C009 `MasterVideoArtifact` only
- both false => exact verified C004 `FinalVideoArtifact` only
- required C009 missing/failing => NEVER fall back to C004

C009A durable identity uses `MasterInputDigest`, not invented aliases.

## Source integrity and provenance

Input contract from the brief:
- GoalContinuation
- ProductionJob
- ProductionPlan
- ProductionPackage
- MasterCompositionInputV1
- optional MasterVideoArtifact

Recompute the actual frozen ProductionPlan digest with existing Python contract-compatible canonical rules; verify Goal, Creative, Production, C004/C007B/C008B/C009A cross-lineage. Recompute `MasterInputIdentity.Compute` using exact available facts, and use `PostProductionMasterArtifactCatalog.FindVerifiedExactAsync` rather than doing a latest-file search. Use existing managed-root / SHA / bytes / no-reparse validators.

Manifest SHA is provenance/QA-input identity; never inject nondeterministic timestamps or local paths into canonical digests.

## QA media policy

Fixed ffprobe + full FFmpeg decode-to-null:
- exactly 1 H.264/yuv420p video stream
- exact C005 dimensions and 24 fps
- no extra video/subtitle/data/attachment streams
- narration required => exactly 1 AAC-LC / 48 kHz / mono audio
- narration not required => zero audio streams
- C005 frame-count/frame-aware duration tolerance and exact profile mapping
- container and audio budgets per brief; never silently broaden tolerance
- no OCR, AI visual assessment, publishing, network, shell, or caller-selected FFmpeg flags

Use existing C009B `IMasterVideoProcessRunner` / `MasterVideoMediaProbe` when truly reusable without changing C009B ownership. Do NOT duplicate an entire process runner unless there is a demonstrated incompatible contract. C009B remains separately owned; do not edit its files.

## Receipt durability

New root:
`%LOCALAPPDATA%\\PicotooPet\\PostProduction\\DeliveryReceipts\\v1\\<safe-job>-<sha16>\\<qa_input_digest>\\`

Immutable `final-artifact-receipt.json`, PASS only.
Receipt includes:
- qa_profile_id = final-video.qa.windows.v1
- qa_input_digest
- receipt_digest
- PASS outcome
- exact Goal-to-final lineage
- observed deterministic media facts
- verified upstream manifest SHA values
- closed passed_check_ids
- verified_at (not in qa_input_digest)

Restart must validate exact receipt and candidate hashes/manifest identities, detect tamper/conflict, and reuse without repeating expensive decode when all exact inputs and receipt still match. No FAIL receipt.

No absolute paths, authored cue/voiceover text, FFmpeg command, stderr, or raw ffprobe JSON in durable receipt.

## File ownership

Only add new product files, preferably:
- FinalVideoQaContracts.cs
- FinalVideoQaService.cs
- FinalVideoQaMediaProbe.cs (only if needed; reuse C009B probe where possible)
- FinalArtifactReceiptStore.cs
- optional FinalVideoQaLineageValidator.cs

Add independent QA smoke harness under `windows/desktop/tests/PicotooPet.FinalVideoQa.SmokeTests/`.
Do NOT touch shared SmokeTests/Program.cs.

Forbidden:
- Goal Center/UI
- FinalVideoAssemblyService / GoalFinalVideoCoordinator
- C007/C008 producers
- C009A composer/catalog/manifest/contracts/verifier
- C009B mux/probe/process implementation
- ProductionPackage/Production or Core schemas
- publishing / deploy/macos / Natural Motion / Maotai

A narrowly justified assembly or project metadata change requires clear explanation.

## Tests

- all 4 narration/overlay combinations and required-master no-fallback
- exact digest lineage and master-catalog lookup
- tamper/manifest/reparse/root/path/conflicts
- ffprobe strict codec/streams/fps/dimensions
- full decode errors
- frame-aware runtime and AAC tolerance boundaries
- PASS-only receipt, deterministic identity, restart reuse, tamper rejection
- no raw text/path/command/stderr leaks
- independent smoke + Python contract/security
- Windows Release build and relevant C009A/C009B regressions
- real Windows C005 24fps media acceptance; if running on macOS, report UNVERIFIED explicitly

If C009B CI reveals a semantic blocker that invalidates your integration base, stop and report rather than modify C009B. Ordinary analyzer/comment issues may be handled by orchestrator.

## Delivery

Implement, test, commit all C010A code and push to `origin/feature/final-video-qa-receipt-core-v1`; clean working tree.
No merge/rebase/tag/release.

Final report:
remote branch; remote HEAD SHA; exact file ownership; CI/tests (verified versus unverified); QA/candidate contract; receipt identity/reuse; architecture notes; residual risks; git status --short.
