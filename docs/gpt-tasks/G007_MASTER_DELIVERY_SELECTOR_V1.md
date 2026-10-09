# G007 — Goal Center Master Delivery Selector v1

Docs-only architecture task. Do not implement code.

## Goal
Design the smallest C009C/Goal Center integration that makes the user open the best final artifact without breaking C004 fallback.

Current facts:
- C004 produces visual-only final MP4 and Goal Center can open it
- C007B produces narration WAV artifacts
- C008B produces derived overlay MP4 when overlays exist
- G004 chose C009 master compositor: use C008B-derived MP4 when overlays exist, then mux narration with video stream-copy
- C009 will produce mastered final MP4
- C010 will later QA and issue Delivery Receipt

## Must decide

1. What is the single "delivery candidate" abstraction?
2. Priority:
   - C010 QA-approved C009 master
   - C009 master before C010 exists?
   - C004 fallback only when narration=false AND overlay=false
3. How Goal Center knows post-production is required:
   - narration_required
   - overlays_required
4. If post-production is required but C009 is missing/failed, must C004 be hidden rather than offered as final?
5. What user-facing states are needed:
   - visual ready / post-processing
   - mastered ready
   - QA failed
   - fallback ready
6. How restart reconstructs state from durable manifests instead of memory-only dictionaries.
7. What minimal read-only local artifact catalog/lookup is needed.
8. How "Open final video" selects one verified managed path.
9. No automatic publishing.
10. No duplicate Goal lifecycle/DB.

## Critical audit
Audit actual:
- GoalFinalVideoCoordinator
- FinalVideoAssemblyService
- GoalVideoContinuationViewModel / Goal Center bindings
- C007B artifact service
- C008B artifact service
- G004 C009 contract

Decide whether C009C should:
A. minimally evolve GoalFinalVideoCoordinator into a delivery selector
or
B. add a new PostProductionDeliveryCoordinator above C004 and leave C004 coordinator untouched.

Choose one based on file ownership, restart safety, and minimal duplication.

## Boundaries
- docs only
- no C004 implementation change now
- no C007/C008 implementation change
- no C009 implementation
- no ProductionPackage mutation
- no publishing
- no Maotai/Natural Motion

## Deliver
docs/architecture/video/G007_MASTER_DELIVERY_SELECTOR_V1.md

Must include:
- CURRENT FLOW
- TARGET FLOW
- DELIVERY CANDIDATE CONTRACT
- PRIORITY/FALLBACK RULES
- STATE MACHINE
- RESTART DISCOVERY
- FILE OWNERSHIP
- ERROR/USER STATUS MAPPING
- TEST MATRIX
- IMPLEMENTATION SLICE
- AGENT RECOMMENDATION
- READY_TO_IMPLEMENT
- BLOCKERS
