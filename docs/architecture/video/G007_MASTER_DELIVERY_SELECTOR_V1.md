# G007 — Goal Center Master Delivery Selector v1

Status: architecture complete; docs-only  
Branch: design/master-delivery-selector-v1

## 1. Purpose

Design the smallest Goal Center delivery-selection layer that opens the semantically complete, verified final video for the current Goal without changing C004 assembly semantics, rebuilding any Production lifecycle, or introducing a second Goal lifecycle/database.

The decisive rule is:

> Goal Center opens the highest-authority artifact that is semantically complete for the current Core-authored post-production requirements.

C004 is a visual assembly artifact and remains a valid fallback only when neither narration nor overlays are required.

C009 is the mastered final whenever post-production is required.

C010, once shipped and enforced, is the final approval authority for the candidate selected by the same rules.

---

# CURRENT FLOW

## 2. C004 Goal delivery today

Current Goal Center wiring is:

```text
GoalVideoContinuationViewModel
        ↓
IGoalFinalVideoObserver
        ↓
GoalFinalVideoCoordinator
        ↓
FinalVideoAssemblyService
        ↓
C004 FinalVideoArtifact
        ↓
OpenFinalVideo()
```

`ControlCenterSession` constructs one `GoalFinalVideoCoordinator` and exposes it as:

```text
FinalVideoDelivery
```

`OperatorHomePageViewModel` injects that observer into `GoalVideoContinuationViewModel`.

Goal Center XAML shows the existing "Open final video" button whenever:

```text
VideoContinuation.CanOpenFinalVideo == true
```

The click handler delegates to:

```text
VideoContinuation.OpenFinalVideo()
```

Therefore the UI already has an appropriate single "open final" action. G007 does not need a second button.

## 3. C004 coordinator limitations

`GoalFinalVideoCoordinator` currently keeps process-only state:

- `_runningJobs`
- `_failedJobs`
- `_artifacts`

Its phases are only:

- Idle
- Assembling
- Ready
- Failed

It does not know:

- NarrationPlan
- `narration_required`
- CaptionOverlayPlan
- `overlays_required`
- C007B WAV artifacts
- C008B derived visual artifact
- C009 master
- C010 receipt

On application restart those dictionaries are empty.

C004 itself is restart-safe because `FinalVideoAssemblyService.AssembleAsync()` verifies and reuses its managed manifest/file pair, but the Goal coordinator's delivery projection is not durable.

This is acceptable for C004. It is not sufficient for final post-production delivery selection.

## 4. C004 artifact facts

C004 produces:

```text
%LOCALAPPDATA%\PicotooPet\FinalVideos\
    final-<job-identity>.mp4
    final-<job-identity>.final-video.json
```

The manifest binds:

- production_job_id
- production_package_id
- production_package_digest
- ordered source output hashes
- final filename
- final SHA
- final bytes

Reuse rechecks:

- managed root
- ordinary files
- no link escape
- package identity
- source hashes
- actual output SHA
- actual bytes

C004 therefore remains a strong verified **visual source/fallback artifact**.

It does not contain narration or C008 overlays.

---

## 5. C007 requirement authority

C007A NarrationPlanV1 is Core-authored and contains:

- production_job_id
- creative_package_id/digest
- production_plan_digest
- target_runtime_ms
- `narration_required`
- narration_plan_digest

The contract enforces:

```text
narration_required == bool(segments)
```

C007B is implemented on its own branch and creates restart-safe local WAV artifacts plus an immutable narration manifest.

C007B does not mux video.

Therefore G007 must read `narration_required` from the Core plan, not infer it from whether a WAV happens to exist.

---

## 6. C008 requirement authority

C008A2 CaptionOverlayPlanV1 is Core-authored and contains:

- production_job_id
- creative_package_id/digest
- production_plan_digest
- target_runtime_ms
- output_profile_id
- `overlays_required`
- caption_overlay_plan_digest

The contract enforces:

```text
overlays_required == bool(overlays)
```

C008B is implemented on its own branch and either:

- returns a verified C004 passthrough when overlays are not required, or
- creates a verified H.264 derived MP4 and immutable text-overlay manifest.

Therefore G007 must read `overlays_required` from the Core plan, not infer it from whether an overlay MP4 happens to exist.

---

## 7. C009 contract

G004 freezes:

```text
postproduction_required =
    narration_required || overlays_required
```

When required, C009 owns:

```text
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\
  <bounded-job-key>\
    <master-composition-digest>\
      master.mp4
      master-manifest.json
```

Its manifest binds the C004/C007/C008 lineage and final output SHA/bytes.

G004 explicitly says Goal Center must prefer C009 master when post-production is required and must not silently fall back to C004.

At the audited repository state, G004 architecture is present but no C009 implementation branch was found. G007 therefore defines the integration contract but must not guess concrete C009 implementation type names that have not landed.

---

## 8. C010 contract status

The current repository contains G006's C010 design task, but no landed C010 QA/receipt implementation contract was found at this audit point.

G007 therefore freezes the selector-side policy and an interface boundary for a future read-only receipt catalog without inventing C010's final storage/type names.

---

# TARGET FLOW

## 9. Target Goal Center flow

```text
Mac Core continuation says production_ready
        |
        +--> C007 NarrationPlan ---------- narration_required
        |
        +--> C008 CaptionOverlayPlan ----- overlays_required
        |
        v
PostProductionDeliveryCoordinator
        |
        +--> ensure/verify C004 visual artifact
        |
        +--> if post-production required:
        |       ensure/reuse C007B if narration required
        |       ensure/reuse C008B if overlays required
        |       ensure/reuse exact C009 master
        |
        +--> if C010 enforcement exists:
        |       find/verify exact receipt for selected candidate
        |
        v
GoalDeliveryCandidateV1
        |
        v
GoalVideoContinuationViewModel
        |
        v
existing "Open final video" button
```

No second Goal record/status table is introduced.

The state is a local projection over:

- durable Core continuation/plans
- verified local managed manifests
- future C010 receipt

---

# ARCHITECTURE DECISION

## 10. Choose B — new PostProductionDeliveryCoordinator

Create a new coordinator above C004/C007/C008/C009.

Do **not** evolve `GoalFinalVideoCoordinator` into the master selector.

### Why

1. **C004 semantics stay frozen.**  
   `GoalFinalVideoCoordinator` currently means visual-only C004 assembly. Adding C009/C010 would change that component's meaning.

2. **Parallel ownership stays clean.**  
   G007 is explicitly forbidden from changing C004 implementation now. A new coordinator avoids touching `GoalFinalVideoCoordinator.cs` and `FinalVideoAssemblyService.cs`.

3. **Restart safety is easier.**  
   A new coordinator can reconstruct its projection from Core plans and durable local manifests instead of inheriting C004 coordinator's process-only dictionaries.

4. **No artifact type masquerading.**  
   A C009 master must never be represented as a `FinalVideoArtifact` merely because C004 already has that type.

5. **C010 integrates naturally above both master and fallback.**  
   QA approves a delivery candidate. It does not belong inside C004 assembly.

6. **The Goal UI can remain single-action.**  
   Only the observer/coordinator injected into `GoalVideoContinuationViewModel` changes. The button remains "Open final video."

---

# DELIVERY CANDIDATE CONTRACT

## 11. Single candidate abstraction

Recommended in-memory contract:

```text
GoalDeliveryCandidateV1

kind:
    c009_master
    c004_fallback

approval:
    artifact_verified
    qa_approved

production_job_id
production_package_id
production_package_digest
production_plan_digest

target_runtime_ms
output_profile_id

narration_required
overlays_required
narration_plan_digest
caption_overlay_plan_digest

file_path
manifest_path
file_sha256
file_bytes

master_composition_digest?   # master only

delivery_receipt_digest?     # only after C010 approval
```

### Important

`file_path` and `manifest_path` are trusted **in-memory local values only**.

They are not:

- Core API fields
- UI input
- user input
- Creative fields
- ProductionPackage fields

No caller selects a file.

## 12. Candidate is singular

For one current Production Job, the selector exposes at most one current delivery candidate.

It does not return a menu of:

- C004
- C008B
- C009
- old masters

The user presses one "Open final video" action.

The selector decides which artifact is valid.

---

# PRIORITY / FALLBACK RULES

## 13. Requirement determination happens first

Always determine:

```text
narration_required = C007A NarrationPlan.narration_required
overlays_required  = C008A2 CaptionOverlayPlan.overlays_required

postproduction_required =
    narration_required || overlays_required
```

Artifact existence never changes those requirements.

This prevents an absent C007B/C008B/C009 file from being misinterpreted as "not required."

---

## 14. Post-production required

If:

```text
narration_required == true
OR
overlays_required == true
```

then:

```text
C004 IS NOT A FINAL DELIVERY CANDIDATE
```

C004 remains an internal visual source for C008/C009.

### Why

If narration is required, opening C004 silently removes authored speech.

If overlays are required, opening C004 silently removes authored on-screen content.

The file may be technically playable, but it is semantically incomplete.

A technically valid incomplete artifact must not be presented as "final video."

---

## 15. No post-production required

Only when:

```text
narration_required == false
AND
overlays_required == false
```

may the verified C004 artifact become:

```text
kind = c004_fallback
```

C009 is not required and should not be created merely to rename/copy C004.

---

## 16. Master priority

When post-production is required:

1. exact QA-approved C009 master, when C010 enforcement is active
2. exact artifact-verified C009 master, only while C010 has not yet shipped/enforced
3. nothing

There is no C004 fallback in this branch.

---

## 17. C009 before C010 exists

Decision:

> YES — before C010 exists in the installed product, an exact C009 master that passes C009's own immutable manifest/file verification may be opened as the mastered final.

User-facing state:

```text
MasteredReady
```

It must not be described internally as "QA approved."

This allows C009C to ship before C010 without making Goal Center unusable.

### After C010 becomes an enforced product capability

Once the build integrates C010 as the delivery gate:

- candidate exists + no receipt yet -> QualityChecking / not open
- PASS receipt -> DeliveryReady / open
- FAIL receipt -> QaFailed / not open

The selector must not dynamically "pretend C010 is absent" just because a receipt is missing.

Whether QA is enforced is a composition/version fact, not a caller toggle.

---

## 18. C004 fallback before/after C010

When no post-production is required:

### Before C010 enforcement

Verified C004:

```text
FallbackReady
CanOpen = true
```

### After C010 enforcement

Verified C004 becomes the C010 candidate.

Until PASS receipt:

```text
QualityChecking
CanOpen = false
```

PASS:

```text
DeliveryReady
kind = c004_fallback
CanOpen = true
```

FAIL:

```text
QaFailed
CanOpen = false
```

---

## 19. Stale master rule

Never select a C009 artifact merely because a `master.mp4` exists.

The master must match current verified lineage:

- production_job_id
- production_package_id/digest
- production_plan_digest
- narration plan digest
- caption overlay plan digest
- narration_required
- overlays_required
- current selected visual lineage
- current master composition digest

An older valid master for a previous digest remains immutable history but is not current delivery.

---

# STATE MACHINE

## 20. Delivery phases

Recommended new local projection enum:

```text
Idle
VisualPreparing
VisualReadyPostProcessing
PostProcessing
MasteredReady
FallbackReady
QualityChecking
DeliveryReady
QaFailed
Failed
```

No new Core Goal status is added.

These are Windows UI/projection states only.

---

## 21. State transitions

```text
Goal not production_ready
        |
        v
Idle

production_ready
        |
        v
VisualPreparing
        |
        +---- C004 invalid/fails ----------------------> Failed
        |
        v
C004 verified
        |
        +---- narration=false, overlays=false --------+
        |                                             |
        |                           C010 not enforced  |
        |                                             v
        |                                       FallbackReady
        |                                             |
        |                                             +--> Open
        |
        |                           C010 enforced
        |                                             |
        |                                             v
        |                                       QualityChecking
        |                                         /        \
        |                                      PASS        FAIL
        |                                       |            |
        |                                       v            v
        |                                DeliveryReady    QaFailed
        |
        +---- narration=true OR overlays=true ----------+
                                                      |
                                                      v
                                     VisualReadyPostProcessing
                                                      |
                                                      v
                                            PostProcessing
                                              /          \
                                    C009 valid           failed/missing
                                        |                   |
                                        v                   v
                             C010 not enforced            Failed
                                        |
                                        v
                                  MasteredReady
                                        |
                                        +--> Open

                             C010 enforced
                                        |
                                        v
                                 QualityChecking
                                   /          \
                                PASS          FAIL
                                 |              |
                                 v              v
                          DeliveryReady      QaFailed
                                 |
                                 +--> Open
```

### Missing C009 while required

If C009 work is currently running:

```text
PostProcessing
```

If the C009 attempt has definitively failed:

```text
Failed
```

In neither case does the state become `FallbackReady`.

---

# ERROR / USER STATUS MAPPING

## 22. User-visible status text

Recommended mappings:

| Phase | User-facing meaning |
|---|---|
| Idle | waiting for Production |
| VisualPreparing | 正在准备基础视频 |
| VisualReadyPostProcessing | 基础画面已完成，正在准备旁白/文字后期 |
| PostProcessing | 正在生成最终成片 |
| MasteredReady | 最终成片已就绪 |
| FallbackReady | 最终视频已就绪 |
| QualityChecking | 最终成片已生成，正在进行交付检查 |
| DeliveryReady | 最终视频已通过检查 |
| QaFailed | 最终视频未通过交付检查 |
| Failed | 最终视频暂未生成成功；已有源产物未被修改 |

Do not expose:

- raw FFmpeg errors
- absolute paths
- narration/overlay raw text
- manifest JSON
- stack traces

---

# RESTART DISCOVERY

## 23. No delivery authority from memory dictionaries

`PostProductionDeliveryCoordinator` may keep in-process:

- currently running job IDs
- current snapshot
- cancellation/task handles

But these are concurrency aids only.

They are not delivery truth.

On a new process, the coordinator reconstructs state from durable facts.

---

## 24. Restart reconstruction order

For a production-ready Goal:

### Step 1 — load current Core lineage

Use current continuation / Production facts to identify:

- goal_id
- production_job_id
- current Production status/package

### Step 2 — obtain C007/C008 Core plans

Read the authenticated deterministic plans:

```text
NarrationPlanResponse
CaptionOverlayPlanResponse
```

Validate:

- same production_job_id
- same creative package lineage
- same production_plan_digest
- same target runtime
- closed profiles

These two plans are the durable requirement authority.

### Step 3 — verify/reuse C004

Use the existing C004 assembler/service as the canonical C004 verification/reuse boundary.

Do not duplicate its private manifest parser in G007.

Calling `FinalVideoAssemblyService.AssembleAsync(jobId)` after restart is acceptable because it:

- verifies/reuses the exact C004 artifact when present
- deterministically recreates it only when the verified Production Package requires it
- does not alter Core Production facts

G007 does not need a second C004 catalog.

### Step 4 — when post-production is required

Reuse the existing services:

- C007B synthesis service for narration-required plans
- C008B overlay service for overlay-required plans
- C009 compositor/service for the exact master

Each service already/should implement manifest-backed reuse.

This reconstructs current post-production state from immutable inputs rather than process memory.

### Step 5 — C009 read-only lookup

C009 should expose the read-only artifact catalog anticipated by G004, e.g. conceptually:

```text
IPostProductionMasterArtifactCatalog
    FindVerifiedExact(...)
```

The catalog:

- owns only the fixed C009 managed root
- resolves only the expected job/digest directory
- validates manifest + output
- returns no result for stale/nonmatching masters
- never accepts arbitrary caller paths

The selector must not recursively choose "the newest MP4."

### Step 6 — future C010 lookup

C010 should expose an equivalent read-only receipt lookup:

```text
IFinalDeliveryReceiptCatalog
    FindExact(candidate identity)
```

G007 does not define C010's physical root before G006 freezes it.

The receipt lookup must bind the exact candidate SHA/identity, not merely production_job_id.

---

## 25. Minimal artifact catalog policy

Do **not** build a general local SQL asset database for G007.

Required lookup surface is only:

1. C004: existing assembler verify/reuse boundary
2. C007B: existing managed manifest reuse
3. C008B: existing managed manifest reuse
4. C009: exact digest/job managed manifest catalog
5. C010: future exact receipt catalog

All are rebuildable from managed manifests/Core plans.

No second durable authority is needed.

---

# OPEN FINAL VIDEO

## 26. Selection and open must be separate

`Observe` / reconcile selects a candidate.

`OpenCurrent` must **reverify** the current candidate immediately before shell launch.

It must not trust only the previous UI snapshot.

---

## 27. Open-time verification

For the current candidate:

1. candidate must be in an openable phase
2. production_job_id must still match current Goal projection
3. candidate kind must still be allowed by current narration/overlay requirements
4. resolve/check the kind-specific managed root
5. manifest must be an ordinary managed file
6. video must be an ordinary managed file
7. reject symlink/reparse escape
8. bytes must equal candidate/manifest
9. recompute SHA-256 and match
10. manifest lineage must still match the selected candidate
11. when C010 is enforced, exact PASS receipt must still verify and bind this candidate
12. only then call the shell launcher

If any check fails:

```text
CanOpen = false
OpenCurrent = false
```

and reconcile again.

---

## 28. Managed roots

Closed roots:

### C004 fallback

```text
%LOCALAPPDATA%\PicotooPet\FinalVideos
```

### C009 master

```text
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1
```

No arbitrary path supplied by:

- Goal
- Creative
- Core API
- UI
- manifest field outside its own fixed root

may be opened.

`ShellFinalVideoLauncher` remains a final launch primitive, not a trust boundary.

The new delivery coordinator must pass it only an already reverified managed file.

---

# C009/C010 PRIORITY TABLE

## 29. Final selection matrix

| narration | overlays | C009 | C010 mode/result | Delivery |
|---|---|---|---|---|
| false | false | none/ignored | not enforced | verified C004 fallback |
| false | false | none/ignored | enforced + pending | no open |
| false | false | none/ignored | PASS on C004 | C004 fallback |
| false | false | none/ignored | FAIL | no open / QaFailed |
| true/false | true/false, any required | missing/running | any | no C004 final; PostProcessing |
| any required | any required | failed | any | no C004 final; Failed |
| any required | any required | exact valid | not enforced | C009 master |
| any required | any required | exact valid | enforced + pending | no open / QualityChecking |
| any required | any required | exact valid | PASS on master | C009 master |
| any required | any required | exact valid | FAIL | no open / QaFailed |

A C009 master for a no-post-production-required job is not selected.

A QA receipt cannot override the semantic fallback rule.

---

# FILE OWNERSHIP

## 30. G007 docs-only ownership

This architecture task owns only:

```text
docs/architecture/video/G007_MASTER_DELIVERY_SELECTOR_V1.md
```

No implementation file is modified by G007.

---

## 31. Recommended implementation ownership — C009C

Preferred new files:

```text
windows/desktop/src/PicotooPet.Desktop/Services/
    PostProductionDeliveryCoordinator.cs
    GoalDeliveryContracts.cs
```

If C009 does not already land an artifact catalog:

```text
PostProductionMasterArtifactCatalog.cs
```

belongs to C009 ownership, not to G007/C009C duplication.

### Minimal integration files

After C009 is stable, C009C likely needs narrow edits to:

```text
windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs
windows/desktop/src/PicotooPet.Desktop/ViewModels/GoalVideoContinuationViewModel.cs
windows/desktop/src/PicotooPet.Desktop/ViewModels/OperatorHomePageViewModel.cs
```

Purpose:

- construct/dispose the new delivery coordinator
- inject the new delivery observer
- continue exposing `CanOpenFinalVideo` and existing open action

The existing Goal Center XAML/button can remain unchanged unless product wording is intentionally revised.

### Tests

Prefer a new isolated test file/project owned by C009C to avoid shared `Program.cs` conflicts where possible.

---

## 32. Explicitly forbidden implementation changes

Do not modify:

### C004

```text
FinalVideoAssemblyService.cs
GoalFinalVideoCoordinator.cs
ControlCenterSession.FinalVideo.cs
C004 manifest semantics
C004 tests except running regressions
```

### C007

```text
Narration Core plan/compiler
WindowsNarrationSynthesisService.cs
C007 contracts/client
C007 artifact manifest
```

### C008

```text
CaptionOverlay Core plan/compiler
WindowsCaptionOverlayService.cs
WindowsCaptionOverlayRenderer.cs
font/glyph policy
C008 artifact manifest
```

### C009 core compositor slice

C009C consumes the frozen C009 service/catalog; it does not rewrite compositor/audio behavior.

### Other

```text
ProductionPackage
src/picotoopet_core/production/**
Goal lifecycle/database
Maotai/UI
Natural Motion
deploy/macos/**
publishing/export
```

No automatic publishing is added.

---

# TEST MATRIX

## 33. Requirement selection

- narration=false, overlays=false -> fallback policy
- narration=true, overlays=false -> master required
- narration=false, overlays=true -> master required
- narration=true, overlays=true -> master required
- requirement flags come from Core plans, not local artifact existence
- mismatched C007/C008 production job rejected
- mismatched production_plan_digest rejected
- mismatched target runtime rejected

## 34. Fallback safety

- C004 present + no post-production required -> candidate
- C004 present + narration required -> not a delivery candidate
- C004 present + overlays required -> not a delivery candidate
- C004 present + required C009 failed -> still not offered
- stale C009 master does not cause fallback policy to change

## 35. Master priority

- exact C009 master beats C004 whenever post-production is required
- master output SHA tamper -> not selected
- master manifest tamper -> not selected
- wrong plan digest -> not selected
- wrong narration plan digest -> not selected
- wrong overlay plan digest -> not selected
- old valid master for previous digest -> not selected

## 36. Pre-C010 behavior

- exact valid C009 master -> MasteredReady + CanOpen
- no-postproduction exact C004 -> FallbackReady + CanOpen
- no artifact -> not open
- UI never labels candidate QA-approved

## 37. C010-enforced behavior

- exact candidate + no receipt -> QualityChecking + cannot open
- exact PASS receipt -> DeliveryReady + can open
- receipt candidate SHA mismatch -> cannot open
- stale receipt for older master -> cannot open
- FAIL receipt -> QaFailed + cannot open
- post-production required + PASS receipt for C004 -> still rejected
- no-postproduction + PASS receipt for C004 -> open

## 38. Restart

Start process with all in-memory coordinator collections empty.

Cases:

- durable C004 fallback exists -> rediscovered/reverified
- required C009 master exists -> rediscovered/reverified
- C009 master absent but C007B/C008B durable artifacts exist -> resume/compose through existing services
- narration artifact tampered -> no master/open
- overlay artifact tampered -> no master/open
- C009 manifest/output tampered -> no master/open
- future PASS receipt survives restart and restores DeliveryReady
- future FAIL receipt survives restart and restores QaFailed

No test should require a previous in-memory dictionary entry.

## 39. Open-time security

- ordinary expected C004 file opens
- ordinary expected C009 file opens
- arbitrary external MP4 rejected
- candidate path moved outside root rejected
- candidate replaced by symlink/reparse rejected
- bytes changed after Ready snapshot rejected
- SHA changed after Ready snapshot rejected
- manifest removed after Ready snapshot rejected
- receipt removed/tampered after Ready snapshot rejected when QA enforced
- launcher is not called on verification failure

## 40. UI projection

- CanOpenFinalVideo false during VisualPreparing
- false during VisualReadyPostProcessing
- false during PostProcessing
- true for MasteredReady only before C010 enforcement
- true for FallbackReady only before C010 enforcement
- false during QualityChecking
- true during DeliveryReady
- false for QaFailed/Failed
- existing Open button remains a single action
- safe status text does not expose local paths/errors

## 41. Regression

- C004 assembly/reuse tests unchanged and green
- C007A/C007B tests green
- C008A/C008B tests green
- C009 tests green
- Goal Center continuation/autopilot behavior unchanged
- Desktop Release build green
- no Production regression
- no automatic publishing action introduced

---

# IMPLEMENTATION SLICE

## 42. C009C — Goal Master Delivery Selector

Implement only after C009A/B artifact/service contract is frozen.

Recommended scope:

1. add `GoalDeliveryCandidateV1` and local delivery-phase contract
2. add `PostProductionDeliveryCoordinator`
3. read/validate C007/C008 requirement plans
4. reuse C004 verify/reuse boundary
5. when required, reuse C007B/C008B and exact C009 master service/catalog
6. project:
   - VisualPreparing
   - VisualReadyPostProcessing
   - PostProcessing
   - MasteredReady
   - FallbackReady
   - Failed
7. reverify the selected managed artifact at open time
8. replace Goal Center's injected C004-only observer with the new coordinator
9. preserve the existing single Open final video button/property names
10. no C010 dependency in the first shipping slice if C010 has not landed

### Follow-up C010 integration slice

After C010 receipt contract lands:

1. inject the read-only receipt catalog/QA coordinator
2. enable compile-time/composition-level QA enforcement
3. add:
   - QualityChecking
   - DeliveryReady
   - QaFailed
4. require exact PASS receipt before `CanOpenFinalVideo=true`
5. do not change master/fallback semantic selection rules

This keeps C009C implementable before C010 while making the final policy deterministic.

---

# AGENT RECOMMENDATION

Use **Codex** for C009C.

The work is dominated by:

- deterministic state projection
- strict artifact identity
- Windows path/hash verification
- async coordinator lifecycle
- restart/reconciliation tests
- narrow ViewModel/session wiring

Use Claude only as a post-implementation review for:

- state-machine gaps
- manifest/receipt lineage
- fallback semantic correctness

Do not have two agents concurrently modify the same coordinator/session/ViewModel files.

---

# READY_TO_IMPLEMENT

**Architecture: READY.**

**C009C implementation: READY only after C009 master service + immutable master artifact/catalog contract has landed.**

The chosen architecture is frozen:

```text
PostProductionDeliveryCoordinator
        above
C004 + C007 + C008 + C009
```

Do not convert `GoalFinalVideoCoordinator` into the post-production selector.

Priority is frozen:

1. QA-approved exact C009 master when C010 is enforced
2. exact C009 master before C010 exists/enforcement ships
3. C004 fallback only when narration_required=false AND overlays_required=false
4. otherwise nothing is openable

C004 is never silently treated as final when authored narration or overlays are required.

# BLOCKERS

## C009C implementation blocker

The concrete C009 master implementation has not landed in the audited repository.

G004 defines the required master root/manifest and recommends `PostProductionMasterArtifactCatalog`, but G007 must consume the actual landed C009 API/type names rather than invent competing ones.

Therefore C009A/B must finish first.

## C010-enforced delivery blocker

C010 currently has a design task but no audited landed FinalArtifactReceipt implementation/managed receipt catalog.

This does not block the pre-C010 C009C selector.

It blocks only the final QA-enforced states:

- QualityChecking
- DeliveryReady based on receipt
- QaFailed

## Integration-base blocker

C007B and C008B are implemented on independent branches. C009/C009C must run from an integration base that contains their accepted contracts together.

This is sequencing, not an architecture ambiguity.

## No other architecture blocker

No new:

- Goal DB lifecycle
- ProductionPackage field
- publishing system
- arbitrary path chooser
- C004 modification

is required.
