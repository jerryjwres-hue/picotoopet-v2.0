# GPT Task — C009C Goal Delivery Selector Implementation Brief

Docs-only. Do not implement code.

Branch:
design/c009c-implementation-brief-v1

Read:
- docs/architecture/video/G007_MASTER_DELIVERY_SELECTOR_V1.md
- C009A concrete files on this branch:
  - PostProductionMasterContracts.cs
  - PostProductionMasterArtifactCatalog.cs
  - PostProductionMasterCompositorService.cs
- existing GoalFinalVideoCoordinator / GoalVideoContinuationViewModel / Goal Center open-final flow

Goal:
turn G007 into a precise implementation-ready C009C task using the actual C009A service/artifact/catalog types.

Freeze:
- new PostProductionDeliveryCoordinator above C004/C007/C008/C009
- do not modify GoalFinalVideoCoordinator internals
- one Goal Center Open final video action
- if narration_required || overlays_required: C004 can never be final candidate
- pre-C010 valid C009 master => MasteredReady
- no-postprod exact verified C004 => FallbackReady
- missing/failed required master => not fallback
- restart derives from durable manifests/plans, not memory-only state
- Open revalidates exact managed candidate at click time
- C010 receipt-aware states deferred but contract seam must be explicit

Identify exact minimal files to modify, exact state transitions, and exact tests.
Do not guess C009B concrete composer class; C009C should consume C009A service/artifact boundary.

Do not change C004/C007/C008/C009 producers, Production, publishing, Maotai/Natural Motion.

Deliver:
docs/architecture/video/C009C_IMPLEMENTATION_BRIEF_V1.md

End with:
READY_TO_IMPLEMENT
DEPENDENCIES
FILES OWNERSHIP
STATE MACHINE
OPEN FINAL CONTRACT
TESTS
BLOCKERS
