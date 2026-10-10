# C009C — Goal Center Master-First Final Delivery Selector

## Status / dependency
Task prepared; START IMPLEMENTATION ONLY AFTER C009B #66 real Windows mux acceptance PASS and no semantic blocker.

Branch: feature/goal-master-delivery-selector-v1
Base: C009B (includes actual FixedFfmpegMasterVideoComposer).

Read:
docs/architecture/video/C009C_IMPLEMENTATION_BRIEF_V1.md
actual current GoalFinalVideoCoordinator / GoalVideoContinuationViewModel / ControlCenterSession / GoalCenter click handler and C009A artifact/catalog types.

## Frozen requirements
- Add PostProductionDeliveryCoordinator ABOVE existing C004/C007/C008/C009; do not alter producer internals.
- Single Goal Center "Open final video" action; keep existing XAML binding when possible.
- NarrationRequired OR OverlaysRequired => ONLY a verified exact C009 MasterVideoArtifact can be final; C004 is never a final candidate.
- No postprod => verified C004 FinalVideoArtifact only => FallbackReady.
- Pre-C010 valid exact master => MasteredReady.
- Any postprod-required missing/failed C007B/C008B/C009 => Failed/PostProcessing as appropriate, NEVER fallback.
- Reconstruct state after restart from Core plans and durable manifests; not an in-memory registry/latest video scan.
- OpenFinalVideoAsync is asynchronous; SHA/manifest/path/lineage rechecked AT CLICK, after checking current job.
- No stale goal/job crossover; cancellation/dispose never marks Failed; deduplicate periodic observe/reconcile.
- C010 receipt states reserved but not enforced; C010B will integrate them later.
- Never auto-publish.

## Ownership
New: GoalDeliveryContracts.cs, PostProductionDeliveryCoordinator.cs.
Narrow modifications: ControlCenterSession.cs, GoalVideoContinuationViewModel.cs, GoalCenterPanel.xaml.cs.
New independent smoke: PicotooPet.PostProductionDelivery.SmokeTests.

Forbidden: GoalFinalVideoCoordinator.cs, FinalVideoAssemblyService.cs, ControlCenterSession.FinalVideo.cs, all C007/C008/C009A/C009B producers and contracts, Core/Production, other UI, Maotai, Natural Motion, deploy, publishing, shared SmokeTests/Program.cs.

Do not duplicate master artifact catalog, C004 assembler, narration/overlay producers, or change main database.

## Tests
- all 4 combinations of narration/overlay required
- C004 never candidate if any postprod required
- exact master lineage/digest only; stale or tampered rejected
- restart empty memory => recovered from manifests/plans
- interrupted/failed master never fallback
- click-time check after Ready (tamper, swap, reparse, SHA mismatch)
- one Open action, UI-thread nonblocking
- cancellation/job switching/concurrent polling safe
- Windows Release build, focused smokes, relevant C004/C007/C008/C009 regressions

## Delivery
Implement only if #66 real Windows PASS. Then commit/push branch clean, no merge/rebase/tag/release.
Report head, files, tests, state machine, Open contract, residual risk.
