# C009C — Goal Master Delivery Selector Implementation Brief v1

Status: docs-only implementation brief  
Branch: design/c009c-implementation-brief-v1  
Implementation target: C009C after C009B lands

## 1. Objective

Convert the frozen G007 Goal Center delivery-selector architecture into a concrete implementation task using the actual C009A types now present in the repository.

C009C adds one Windows-local delivery coordinator above the existing C004/C007/C008/C009 producer services.

It does not change any producer contract.

The invariant is:

> The Goal Center may expose exactly one "Open final video" action, and that action may open only the exact verified artifact that is semantically complete for the current Core-authored narration/overlay requirements.

If either narration or overlays are required, C004 is never a final delivery candidate.

---

# 2. Audited concrete C009A boundary

C009A is landed at the current design branch baseline and freezes these actual public types.

## 2.1 MasterCompositionInputV1

```csharp
public sealed record MasterCompositionInputV1(
    FinalVideoArtifact C004,
    NarrationPlanResponseRecord NarrationPlan,
    NarrationArtifact? NarrationArtifact,
    CaptionOverlayPlanResponseRecord OverlayPlan,
    TextOverlayArtifact? OverlayArtifact);
```

C009C must construct exactly this type.

Do not create a parallel C009 input contract.

## 2.2 MasterCompositionResult

```csharp
public sealed record MasterCompositionResult(
    bool Required,
    FinalVideoArtifact? C004Fallback,
    MasterVideoArtifact? Artifact);
```

This is the final semantic selection boundary C009C consumes.

Expected shapes:

### no post-production required

```text
Required = false
C004Fallback != null
Artifact = null
```

### post-production required

```text
Required = true
C004Fallback = null
Artifact != null
```

Any other shape is a delivery failure.

## 2.3 MasterVideoArtifact

Actual C009A artifact:

```csharp
public sealed record MasterVideoArtifact(
    string ProductionJobId,
    string ProductionPackageId,
    string ProductionPackageDigest,
    string ProductionPlanDigest,
    string MasterInputDigest,
    string OutputProfileId,
    long TargetRuntimeMs,
    string FilePath,
    string ManifestPath,
    string Sha256,
    long Bytes,
    bool HasAudio,
    string VisualSourceKind,
    bool Reused);
```

C009C must use these exact fields.

Do not rename `MasterInputDigest` to the earlier G004 draft name `MasterCompositionDigest`.

## 2.4 Master artifact root and exact path

C009A owns:

```text
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1
```

The exact managed path is derived by:

- `MasterPathPolicy.JobDirectory(root, productionJobId)`
- `MasterPathPolicy.ArtifactDirectory(jobDirectory, masterInputDigest)`

and fixed names:

- `PostProductionMasterArtifactCatalog.OutputFileName == "master.mp4"`
- `PostProductionMasterArtifactCatalog.ManifestFileName == "master-manifest.json"`

C009C is in the same shipping assembly and may reuse these existing internal path-policy constants for read-only open-time verification.

Do not duplicate the master job/digest path algorithm.

## 2.5 C009A service behavior

Actual API:

```csharp
Task<MasterCompositionResult> ComposeAsync(
    MasterCompositionInputV1 input,
    CancellationToken cancellationToken = default);
```

`PostProductionMasterCompositorService.ComposeAsync()` already:

1. validates NarrationPlan/CaptionOverlayPlan
2. validates cross-stage lineage
3. independently re-verifies C004
4. returns C004 fallback immediately when neither narration nor overlay is required
5. re-verifies C008B when overlays are required
6. re-verifies C007B when narration is required
7. builds `MasterIdentityFacts`
8. computes `MasterInputDigest`
9. calls `PostProductionMasterArtifactCatalog.FindVerifiedExactAsync()`
10. reuses the exact durable master when present
11. otherwise invokes the injected `IMasterVideoComposer`
12. commits immutable `master.mp4 + master-manifest.json`
13. re-opens through the catalog before returning

Therefore C009C must not implement:

- master digest calculation
- master manifest parsing for candidate selection
- recursive artifact search
- "latest master" selection
- C009 source lineage validation
- mux policy

C009A already owns those responsibilities.

---

# 3. C009B dependency boundary

C009B is currently implementing the real `IMasterVideoComposer`.

Frozen C009A interface:

```csharp
public interface IMasterVideoComposer
{
    Task ComposeAsync(
        MasterVideoCompositionRequest request,
        CancellationToken cancellationToken);
}
```

C009C must depend on an already-constructed:

```text
PostProductionMasterCompositorService
```

It must not reference or predict the concrete C009B composer class name.

The only composition-root code that knows the concrete C009B implementation is the final wiring performed after C009B lands.

No C009C coordinator/test contract depends on that concrete class.

---

# 4. Audited upstream services to reuse

## C004

Use existing:

```csharp
IFinalVideoAssembler
FinalVideoAssemblyService.Create(session)
Task<FinalVideoArtifact> AssembleAsync(...)
```

Do not use `GoalFinalVideoCoordinator` as a child coordinator.

C009C needs the C004 artifact/service, not C004's old UI state machine.

## C007

Core plan:

```csharp
ControlCenterSession.GetNarrationPlanAsync(
    string productionJobId,
    CancellationToken cancellationToken)
```

Local artifact service:

```csharp
WindowsNarrationSynthesisService.CreateDefault()

Task<NarrationArtifact> SynthesizeAsync(
    NarrationPlanResponseRecord response,
    CancellationToken cancellationToken)
```

When `NarrationRequired == false`, C009C should not synthesize narration at all; pass `NarrationArtifact = null` to C009A.

## C008

Core plan:

```csharp
ControlCenterSession.GetCaptionOverlayPlanAsync(
    string productionJobId,
    CancellationToken cancellationToken)
```

Local derived visual service:

```csharp
WindowsCaptionOverlayService.Create()

Task<TextOverlayArtifact> ApplyAsync(
    FinalVideoArtifact source,
    CaptionOverlayPlanResponseRecord planResponse,
    CancellationToken cancellationToken)
```

When `OverlaysRequired == false`, C009C should not invoke C008B; pass `OverlayArtifact = null` to C009A.

This avoids creating/handling a C008 passthrough artifact when C009A does not need it.

---

# 5. New C009C contracts

Preferred new file:

```text
windows/desktop/src/PicotooPet.Desktop/Services/GoalDeliveryContracts.cs
```

## 5.1 GoalDeliveryPhase

```text
Idle
VisualPreparing
VisualReadyPostProcessing
PostProcessing
MasteredReady
FallbackReady
QualityChecking       # reserved C010 seam; C009C v1 does not emit
DeliveryReady         # reserved C010 seam; C009C v1 does not emit
QaFailed              # reserved C010 seam; C009C v1 does not emit
Failed
```

C009C pre-C010 emits only:

- Idle
- VisualPreparing
- VisualReadyPostProcessing
- PostProcessing
- MasteredReady
- FallbackReady
- Failed

## 5.2 GoalDeliveryKind

```text
C004Fallback
C009Master
```

No C008B direct-delivery kind exists.

No narration-only kind exists.

## 5.3 GoalDeliveryCandidateV1

Recommended exact in-memory contract:

```text
GoalDeliveryCandidateV1

Kind
ProductionJobId
ProductionPackageId
ProductionPackageDigest
ProductionPlanDigest
TargetRuntimeMs
OutputProfileId

NarrationRequired
NarrationPlanDigest
OverlaysRequired
CaptionOverlayPlanDigest

FilePath
ManifestPath
FileSha256
FileBytes

ManifestSha256
ManifestBytes

MasterInputDigest?       # required only for C009Master

ApprovalReceiptDigest?   # always null in C009C; explicit C010 seam
```

Why `ManifestSha256/ManifestBytes` are added locally:

- C009A/C004 already strictly verify their manifests before returning artifacts.
- C009C hashes that already-verified manifest when creating the delivery candidate.
- Open-time verification can then prove that the same exact manifest bytes still exist without duplicating C004/C009 private manifest parsing.
- on restart, the candidate is rebuilt through the producer service and a fresh manifest hash is derived.

These fields are local in-memory delivery facts only.

They are not added to C004, C009, ProductionPackage, Core, or any persisted manifest.

## 5.4 GoalDeliverySnapshot

```text
GoalDeliverySnapshot

GoalId?
ProductionJobId?
Phase
StatusText?
CanOpen
```

This replaces C004's `GoalFinalVideoSnapshot` only at the Goal Center delivery-observer boundary.

It does not replace or modify the C004 type.

## 5.5 New observer interface

Do not change `IGoalFinalVideoObserver`, because doing so would force modifications to C004's `GoalFinalVideoCoordinator`.

Add:

```csharp
public interface IPostProductionDeliveryObserver
{
    GoalDeliverySnapshot Observe(
        string? goalId,
        GoalVideoContinuationRecord? continuation);

    Task<bool> OpenCurrentAsync(
        CancellationToken cancellationToken = default);
}
```

Open is intentionally async because exact SHA verification of a potentially large final MP4 must not block the WPF UI thread.

---

# 6. New coordinator

Preferred new file:

```text
windows/desktop/src/PicotooPet.Desktop/Services/PostProductionDeliveryCoordinator.cs
```

## 6.1 Dependencies

The coordinator should own only orchestration dependencies:

```text
IFinalVideoAssembler
Func<string, CancellationToken, Task<NarrationPlanResponseRecord>>
Func<string, CancellationToken, Task<CaptionOverlayPlanResponseRecord>>
WindowsNarrationSynthesisService
WindowsCaptionOverlayService
PostProductionMasterCompositorService
IFinalVideoLauncher
Time/lifetime/cancellation primitives as needed
```

Using method-group delegates for the two Core plan fetchers avoids adding a second networking/session abstraction.

Recommended production factory shape:

```text
PostProductionDeliveryCoordinator.Create(
    ControlCenterSession session,
    PostProductionMasterCompositorService masterService)
```

The factory can wire:

- `FinalVideoAssemblyService.Create(session)`
- `session.GetNarrationPlanAsync`
- `session.GetCaptionOverlayPlanAsync`
- `WindowsNarrationSynthesisService.CreateDefault()`
- `WindowsCaptionOverlayService.Create()`
- provided `masterService`
- `new ShellFinalVideoLauncher()`

The coordinator must never instantiate or know the concrete C009B composer.

---

# 7. Observe contract

`Observe(goalId, continuation)` remains synchronous and non-blocking, matching the existing Goal Center polling model.

Valid work requires:

```text
goalId != null
continuation != null
goalId == continuation.GoalId
continuation.ProductionJobId non-empty
continuation.ProductionStatus == "production_ready"
```

Otherwise return/reset to `Idle`.

For an eligible job:

- if a verified in-process candidate for the same job is already current, return its ready snapshot
- if reconciliation is already running, return current running phase
- otherwise schedule exactly one reconciliation task for the job and return `VisualPreparing`

In-memory running/failed/candidate dictionaries are allowed only as process-local concurrency/UI caches.

They are not durable authority.

A fresh process must reach the same result without them.

---

# 8. Reconcile algorithm

For one production-ready job:

## Step 1 — fetch both Core plans

Fetch:

- `NarrationPlanResponseRecord`
- `CaptionOverlayPlanResponseRecord`

Prefer parallel fetch with shared cancellation if implementation remains simple.

Validate their existing strict contracts.

Then perform an early cross-plan delivery check before deciding fallback:

```text
NarrationPlan.Plan.ProductionJobId == productionJobId
OverlayPlan.Plan.ProductionJobId == productionJobId

NarrationPlan.Plan.CreativePackageId
    == OverlayPlan.Plan.CreativePackageId

NarrationPlan.Plan.CreativePackageDigest
    == OverlayPlan.Plan.CreativePackageDigest

NarrationPlan.Plan.ProductionPlanDigest
    == OverlayPlan.Plan.ProductionPlanDigest

NarrationPlan.Plan.TargetRuntimeMs
    == OverlayPlan.Plan.TargetRuntimeMs
```

If any mismatch exists:

```text
Failed
CanOpen = false
```

This early validation is mandatory because fallback policy must never be decided from mismatched plan flags.

## Step 2 — determine semantic requirement

Only after cross-plan validation:

```text
postProductionRequired =
    NarrationPlan.Plan.NarrationRequired
    || OverlayPlan.Plan.OverlaysRequired
```

Artifact existence is not part of this decision.

## Step 3 — verify/reuse C004

Set:

```text
VisualPreparing
```

Call:

```text
IFinalVideoAssembler.AssembleAsync(productionJobId)
```

This either creates or reuses the durable C004 artifact under its existing manifest contract.

Failure:

```text
Failed
CanOpen = false
```

## Step 4A — no post-production required

Do not call C007B.

Do not call C008B.

Construct:

```csharp
new MasterCompositionInputV1(
    c004,
    narrationPlan,
    NarrationArtifact: null,
    overlayPlan,
    OverlayArtifact: null)
```

Call C009A `PostProductionMasterCompositorService.ComposeAsync()`.

Require exact result shape:

```text
result.Required == false
result.C004Fallback != null
result.Artifact == null

result.C004Fallback.ProductionJobId == productionJobId
result.C004Fallback.Sha256 == c004.Sha256
result.C004Fallback.Bytes == c004.Bytes
```

Then derive a `C004Fallback` delivery candidate and transition:

```text
FallbackReady
CanOpen = true
```

C009A creates no master in this mode.

## Step 4B — post-production required

After C004 is verified set:

```text
VisualReadyPostProcessing
```

Then immediately enter:

```text
PostProcessing
```

### narration

If:

```text
NarrationRequired == true
```

call:

```text
WindowsNarrationSynthesisService.SynthesizeAsync(narrationPlan)
```

Otherwise keep:

```text
NarrationArtifact = null
```

### overlays

If:

```text
OverlaysRequired == true
```

call:

```text
WindowsCaptionOverlayService.ApplyAsync(c004, overlayPlan)
```

Require returned artifact:

```text
Passthrough == false
```

Otherwise keep:

```text
OverlayArtifact = null
```

### master

Construct the actual C009A input:

```text
MasterCompositionInputV1(
    c004,
    narrationPlan,
    narrationArtifact,
    overlayPlan,
    overlayArtifact)
```

Call:

```text
PostProductionMasterCompositorService.ComposeAsync(...)
```

Require exact result shape:

```text
result.Required == true
result.C004Fallback == null
result.Artifact != null
```

Also require:

```text
artifact.ProductionJobId == productionJobId
artifact.ProductionPlanDigest == narrationPlan.Plan.ProductionPlanDigest
artifact.OutputProfileId == overlayPlan.Plan.OutputProfileId
artifact.TargetRuntimeMs == narrationPlan.Plan.TargetRuntimeMs
artifact.HasAudio == narrationPlan.Plan.NarrationRequired
```

C009A already checks deeper lineage; these are selector-level assertions.

Create a `C009Master` delivery candidate.

Transition:

```text
MasteredReady
CanOpen = true
```

## Step 5 — any required-stage failure

If C007B, C008B, C009A, or C009B-backed composition fails:

```text
Failed
CanOpen = false
candidate = null
```

Critically:

> Do not convert this branch to C004 fallback.

C004 remains only a source artifact.

---

# 9. Durable restart behavior

C009C does not persist a second coordinator state file.

On application restart the in-memory caches are empty.

The next Goal Center observation performs the same reconcile algorithm.

Reuse occurs through the actual durable producer boundaries:

- C004 `FinalVideoAssemblyService.AssembleAsync()` verifies/reuses C004
- C007B `WindowsNarrationSynthesisService.SynthesizeAsync()` verifies/reuses narration manifest/WAVs
- C008B `WindowsCaptionOverlayService.ApplyAsync()` verifies/reuses derived overlay
- C009A `PostProductionMasterCompositorService.ComposeAsync()` computes exact lineage/digest and calls `PostProductionMasterArtifactCatalog.FindVerifiedExactAsync()`

Therefore:

```text
process memory is cache
managed manifests + Core plans are truth
```

No general local artifact DB is added.

No recursive "find newest master" logic is added.

---

# 10. Delivery candidate materialization

After C004/C009A has already returned a verified artifact, C009C derives its candidate.

For either kind:

1. require file/manifest paths to be fully qualified
2. resolve the appropriate closed managed root internally
3. enforce exact expected path policy
4. require ordinary file + ordinary manifest
5. reject reparse escape
6. read manifest length with a small fixed upper bound
7. compute manifest SHA-256
8. record manifest bytes + digest into `GoalDeliveryCandidateV1`

The video SHA/bytes come from:

- `FinalVideoArtifact.Sha256/Bytes`
- `MasterVideoArtifact.Sha256/Bytes`

Do not replace those producer-authoritative values with UI-supplied values.

---

# 11. Exact path rules for candidate materialization

## C004 fallback

Closed root:

```text
%LOCALAPPDATA%\PicotooPet\FinalVideos
```

Expected filename remains C004's existing frozen rule:

```text
identity = sha256(production_job_id)[0..32]
final-<identity>.mp4
final-<identity>.final-video.json
```

C009C may reproduce this already-frozen filename check in its read-only delivery verifier, but must not parse or rewrite the C004 manifest.

The C004 service has already validated the manifest before candidate construction.

## C009 master

Closed root:

```text
%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1
```

Use existing C009A code directly:

```text
MasterPathPolicy.JobDirectory(...)
MasterPathPolicy.ArtifactDirectory(...)
PostProductionMasterArtifactCatalog.OutputFileName
PostProductionMasterArtifactCatalog.ManifestFileName
```

Expected directory uses:

```text
MasterVideoArtifact.MasterInputDigest
```

Do not independently reconstruct `MasterIdentityFacts` in C009C.

Do not parse/reimplement C009A's private `ManifestMatches` logic.

---

# 12. Open-final contract

## 12.1 One action remains

Keep existing Goal Center button:

```text
打开最终视频
```

No second master/fallback button.

No dropdown.

No "open C004 anyway" escape hatch.

## 12.2 Make open async

Current C004 flow is synchronous:

```text
GoalVideoContinuationViewModel.OpenFinalVideo()
IGoalFinalVideoObserver.OpenCurrent()
```

C009C must not hash a potentially large master MP4 synchronously on the WPF UI thread.

Change only the Goal Center delivery interaction to:

```text
GoalVideoContinuationViewModel.OpenFinalVideoAsync(...)
IPostProductionDeliveryObserver.OpenCurrentAsync(...)
```

and change `GoalCenterPanel.OpenFinalVideo_Click` to `async void` that awaits the ViewModel.

Do not change `IGoalFinalVideoObserver` or `GoalFinalVideoCoordinator`.

## 12.3 OpenCurrentAsync preconditions

Under the coordinator lock, snapshot:

- current Goal ID
- current production job ID
- current phase
- current candidate

Openable pre-C010 phases are only:

```text
FallbackReady
MasteredReady
```

Reserved C010 future:

```text
DeliveryReady
```

Everything else returns false.

The candidate's ProductionJobId must exactly equal the current snapshot ProductionJobId.

## 12.4 Open-time revalidation

Outside the lock, revalidate the exact candidate.

### common

- candidate path and manifest path must match the exact kind-specific managed path
- managed root exists and has no reparse escape
- output is ordinary
- manifest is ordinary
- output bytes equal candidate.FileBytes
- manifest bytes equal candidate.ManifestBytes
- recompute output SHA-256 == candidate.FileSha256
- recompute manifest SHA-256 == candidate.ManifestSha256

### C004Fallback

Additionally require:

```text
NarrationRequired == false
OverlaysRequired == false
MasterInputDigest == null
```

If either requirement bit is true, reject even if the MP4 is intact.

### C009Master

Additionally require:

```text
NarrationRequired || OverlaysRequired
MasterInputDigest is a lowercase 64-char SHA
expected master directory is exactly that digest directory
```

No C004 path may substitute.

## 12.5 Why manifest hashing is sufficient at click time

Candidate selection was produced by:

- strict C004 reuse verification, or
- C009A's strict source validation + exact catalog verification.

C009C then records the digest of that already-verified manifest.

At click time, matching:

- exact deterministic managed path
- exact video hash/bytes
- exact manifest hash/bytes

proves the user is opening the same verified candidate selected during reconciliation.

This avoids duplicating C004/C009 manifest parsers.

If the process restarts, the candidate is rebuilt through the durable producer/catalog path first; no manifest hash from the prior process is trusted.

## 12.6 Launch

Only after all open-time checks pass:

```text
IFinalVideoLauncher.Open(candidate.FilePath)
```

Reuse existing:

```text
ShellFinalVideoLauncher
```

as the final shell-launch primitive.

If verification or launch fails:

- return false
- clear/disable current candidate
- set a safe non-path status
- do not open any fallback automatically

---

# 13. C010 seam

C009C v1 is pre-C010.

The following phases exist only as reserved contract states:

- QualityChecking
- DeliveryReady
- QaFailed

C009C does not emit them.

The delivery candidate already contains the facts future C010 needs to bind a receipt:

- kind
- production job/package identity
- production plan digest
- target runtime
- output profile
- narration requirement + plan digest
- overlay requirement + plan digest
- exact output SHA/bytes
- master input digest when master

A future C010 integration must wrap/approve this exact candidate.

It must not change the semantic selection rule:

```text
required post-production => C009 master only
no post-production       => C004 fallback
```

When C010 is later enforced:

- candidate present + receipt pending -> QualityChecking, no open
- exact PASS receipt -> DeliveryReady, open
- FAIL -> QaFailed, no open

C009C must not add a fake/placeholder receipt file now.

---

# 14. Exact ControlCenterSession integration

Current session owns:

```text
GoalProductionAutopilotCoordinator _productionAutopilot
GoalFinalVideoCoordinator _finalVideoCoordinator
```

and exposes:

```text
IGoalFinalVideoObserver FinalVideoDelivery
```

C009C should stop using the C004-only coordinator as the Goal Center delivery observer.

Do not delete or edit `GoalFinalVideoCoordinator.cs`.

After C009B lands, change session composition to own:

```text
PostProductionDeliveryCoordinator _postProductionDelivery
```

Expose:

```text
IPostProductionDeliveryObserver FinalVideoDelivery
```

Construct the C009A service with the actual C009B-landed `IMasterVideoComposer` in the composition root, then pass that service to:

```text
PostProductionDeliveryCoordinator.Create(this, masterService)
```

C009C brief intentionally does not name the C009B concrete composer class.

Dispose:

```text
await _postProductionDelivery.DisposeAsync()
```

instead of disposing the old Goal Center C004 coordinator.

The standalone `GoalFinalVideoCoordinator` implementation remains intact for C004 regression/unit use.

---

# 15. GoalVideoContinuationViewModel integration

Change only the delivery observer field/constructor type:

from:

```text
IGoalFinalVideoObserver?
```

to:

```text
IPostProductionDeliveryObserver?
```

Keep existing externally-bound properties:

- `CanOpenFinalVideo`
- `StatusText`
- `ProductionStatusText`

`ObserveAutopilot()` continues to call:

```text
var finalSnapshot = _finalVideo.Observe(_goalId, Continuation)
```

and maps:

- `StatusText`
- `CanOpen`

No new Goal Center binding is required.

Replace:

```text
bool OpenFinalVideo()
```

with:

```text
Task<bool> OpenFinalVideoAsync(
    CancellationToken cancellationToken = default)
```

Failure updates the same safe local status and disables open.

---

# 16. Goal Center integration

`GoalCenterPanel.xaml` requires no change.

Keep:

- one `OpenFinalVideoButton`
- `CanOpenFinalVideo` visibility/enable binding
- text `打开最终视频`

Only change the existing code-behind handler:

```text
OpenFinalVideo_Click
```

to async and await:

```text
viewModel.VideoContinuation.OpenFinalVideoAsync()
```

The existing failure message may remain bounded/general.

No master/fallback identity is displayed to the user in v1.

---

# 17. Files that do not need modification

`OperatorHomePageViewModel.cs` does not require a semantic change if:

- `ControlCenterSession.FinalVideoDelivery` keeps the same property name
- `GoalVideoContinuationViewModel` constructor accepts the new observer interface

Its existing construction call remains conceptually:

```text
new GoalVideoContinuationViewModel(
    session,
    session.ProductionAutopilot,
    session.FinalVideoDelivery)
```

Do not modify this file merely to rename concepts.

`GoalCenterPanel.xaml` also does not require modification.

---

# 18. Failure/status mapping

Pre-C010 C009C uses bounded user projection only.

```text
Idle
    status = null / current existing idle wording
    CanOpen = false

VisualPreparing
    status = "正在准备基础视频"
    CanOpen = false

VisualReadyPostProcessing
    status = "基础画面已完成，正在准备旁白/文字后期"
    CanOpen = false

PostProcessing
    status = "正在生成最终成片"
    CanOpen = false

FallbackReady
    status = "最终视频已就绪"
    CanOpen = true

MasteredReady
    status = "最终成片已就绪"
    CanOpen = true

Failed
    status = "最终视频暂未生成成功；已有源产物未被修改。"
    CanOpen = false
```

Do not expose raw exception codes in Goal Center status.

Tests may assert bounded internal error classification separately if useful.

---

# 19. Concurrency and stale-job rules

Follow the existing coordinator pattern:

- one background reconcile task per production job
- changing current Goal/job immediately resets the visible snapshot
- a completion from an old job may populate an internal cache but must not replace the current snapshot
- disposal cancels the coordinator lifetime
- app-shutdown cancellation is not persisted as Failed
- background task collections are drained on dispose

Before publishing a phase/candidate, check:

```text
current goal ID == work goal ID
current production job ID == work production job ID
```

No old Goal's master may become the current candidate.

---

# 20. No-fallback hard invariant

The implementation should centralize one predicate:

```text
postProductionRequired =
    narrationPlan.Plan.NarrationRequired
    || overlayPlan.Plan.OverlaysRequired
```

Then enforce:

```text
if postProductionRequired:
    the only openable candidate kind is C009Master
else:
    the only openable candidate kind is C004Fallback
```

This invariant must be checked:

1. during candidate construction
2. before setting a Ready phase
3. again in `OpenCurrentAsync`

A C004 artifact must never become openable merely because:

- narration synthesis failed
- overlay rendering failed
- master mux failed
- master is missing
- master catalog conflicts
- C009B executable is unavailable

Those cases are `Failed`, not `FallbackReady`.

---

# 21. Tests

Prefer a new isolated C009C smoke/unit harness rather than editing shared C007/C008/C009 test Program files.

Recommended:

```text
windows/desktop/tests/PicotooPet.PostProductionDelivery.SmokeTests/
```

If adding a project to a shared solution would create ownership conflict, keep it isolated and invoke directly.

## 21.1 State/requirement matrix

Test all four Core plan modes:

| narration | overlays | expected |
|---|---|---|
| false | false | FallbackReady / C004Fallback |
| true | false | MasteredReady / C009Master |
| false | true | MasteredReady / C009Master |
| true | true | MasteredReady / C009Master |

Assertions:

- requirement comes from plans
- artifact existence never changes requirement
- cross-plan job mismatch -> Failed
- creative package mismatch -> Failed
- production_plan_digest mismatch -> Failed
- target runtime mismatch -> Failed

## 21.2 Exact C009A result-shape tests

No-postproduction:

- C009A `Required=false`
- fallback non-null
- master null
- only then FallbackReady

Required:

- `Required=true`
- fallback null
- artifact non-null
- only then MasteredReady

Malformed/inconsistent fake result shape -> Failed.

## 21.3 No-fallback tests

For each required mode, inject failures at:

- C007B synthesis
- C008B render/reuse
- C009A source verification
- C009 catalog conflict
- C009B composer failure

Every case:

```text
Phase = Failed
CanOpen = false
candidate = null
```

C004 launcher is never called.

## 21.4 Restart tests

Start a completely new coordinator with no prior memory.

Cases:

- existing C004 + no postprod -> services reuse -> FallbackReady
- existing narration + master -> C007B/C009A reuse -> MasteredReady
- existing overlay + master -> C008B/C009A reuse -> MasteredReady
- existing overlay+narration+master -> all durable reuse -> MasteredReady
- stale master at wrong `MasterInputDigest` is ignored; exact C009A logic composes/finds the current digest
- tampered exact master -> C009A catalog conflict -> Failed
- tampered narration -> C009A/C007B fails -> Failed
- tampered overlay -> C008B/C009A fails -> Failed

No restart test may seed a coordinator candidate dictionary.

## 21.5 Candidate materialization tests

C004:

- exact managed file + manifest accepted
- wrong final filename rejected
- output outside FinalVideos rejected
- reparse output rejected
- reparse manifest rejected
- manifest SHA captured after producer verification

C009:

- exact `MasterPathPolicy` directory accepted
- wrong job directory rejected
- wrong digest directory rejected
- wrong master filename rejected
- wrong manifest filename rejected
- path outside Master/v1 rejected
- manifest SHA captured after C009A catalog verification

## 21.6 Open-time tests

After Ready, mutate one thing at a time:

- output deleted
- output bytes changed
- output replaced
- output converted to reparse point
- manifest deleted
- manifest bytes changed
- manifest replaced
- manifest converted to reparse point

Expected:

```text
OpenCurrentAsync == false
launcher not called
CanOpen becomes false
```

Valid untouched C004 fallback:

```text
launcher called exactly once with exact managed C004 path
```

Valid untouched C009 master:

```text
launcher called exactly once with exact managed master path
```

Required candidate with C004 kind manually injected in test:

```text
rejected
```

No-postproduction candidate with C009 kind manually injected:

```text
rejected
```

## 21.7 Async UI/open tests

- `OpenFinalVideoAsync` awaits observer
- failed open updates bounded status and disables button
- Goal Center click handler awaits once
- no synchronous large-file hash on WPF UI path
- existing button remains the only open-final control
- XAML binding names unchanged

## 21.8 Concurrency

- repeated 5-second Observe while running creates only one job task
- old job completion cannot overwrite new current Goal state
- cancellation on dispose does not report Failed
- ready candidate is scoped by production job ID

## 21.9 Regression

Run:

- C004 focused tests
- C007B focused tests
- C008B focused tests
- C009A isolated smokes
- C009B isolated smokes/real Windows acceptance
- Goal continuation tests
- Windows Desktop Release build

Do not modify producer tests to make C009C pass.

---

# READY_TO_IMPLEMENT

**C009C brief: READY.**

**Code implementation may start immediately after C009B lands and its concrete `IMasterVideoComposer` passes acceptance.**

The implementation architecture is frozen:

```text
PostProductionDeliveryCoordinator
    -> C007/C008 Core plans
    -> C004 FinalVideoAssemblyService
    -> C007B / C008B only when required
    -> C009A PostProductionMasterCompositorService
    -> GoalDeliveryCandidateV1
    -> one Goal Center Open final video action
```

C009C must not modify C009A/B producers.

# DEPENDENCIES

Hard dependencies:

1. C009A — already landed
   - `MasterCompositionInputV1`
   - `MasterCompositionResult`
   - `MasterVideoArtifact`
   - `PostProductionMasterCompositorService`
   - `PostProductionMasterArtifactCatalog`
   - `MasterPathPolicy`

2. C009B — must land before C009C code starts
   - real accepted implementation of `IMasterVideoComposer`
   - concrete class name is intentionally not assumed by this brief

3. Existing accepted C004/C007B/C008B implementations on the same integration base.

C010 is **not** a dependency for C009C pre-QA delivery.

The C010 seam is reserved but inactive.

# FILES OWNERSHIP

C009C implementation owns:

New:

```text
windows/desktop/src/PicotooPet.Desktop/Services/
    GoalDeliveryContracts.cs
    PostProductionDeliveryCoordinator.cs
```

Narrow integration edits:

```text
windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.cs
windows/desktop/src/PicotooPet.Desktop/ViewModels/GoalVideoContinuationViewModel.cs
windows/desktop/src/PicotooPet.Desktop/Views/Pages/GoalCenterPanel.xaml.cs
```

Preferred isolated tests:

```text
windows/desktop/tests/PicotooPet.PostProductionDelivery.SmokeTests/**
```

No semantic modification required:

```text
OperatorHomePageViewModel.cs
GoalCenterPanel.xaml
```

Explicitly forbidden:

```text
GoalFinalVideoCoordinator.cs
FinalVideoAssemblyService.cs
ControlCenterSession.FinalVideo.cs

WindowsNarrationSynthesisService.cs
Narration contracts/client/Core

WindowsCaptionOverlayService.cs
WindowsCaptionOverlayRenderer.cs
CaptionOverlay contracts/client/Core

PostProductionMasterContracts.cs
PostProductionMasterArtifactCatalog.cs
PostProductionMasterCompositorService.cs
PostProductionMasterSourceVerifier.cs
IMasterVideoComposer.cs
C009B mux/process/probe files

src/picotoopet_core/production/**
ProductionPackage
publishing
Maotai/UI
Natural Motion
deploy/macos/**
```

# STATE MACHINE

Pre-C010 shipping machine:

```text
not production_ready
    -> Idle

production_ready
    -> VisualPreparing
    -> fetch/validate C007+C008 plans
    -> verify/reuse C004
       |
       +-- narration=false && overlays=false
       |      -> C009A ComposeAsync(null downstream artifacts)
       |      -> Required=false + exact C004 fallback
       |      -> FallbackReady
       |
       +-- narration=true || overlays=true
              -> VisualReadyPostProcessing
              -> PostProcessing
              -> generate/reuse required C007B/C008B
              -> C009A ComposeAsync
                 |
                 +-- exact Required=true master
                 |      -> MasteredReady
                 |
                 +-- any missing/conflict/failure
                        -> Failed
```

Openable:

```text
FallbackReady
MasteredReady
```

Not openable:

```text
Idle
VisualPreparing
VisualReadyPostProcessing
PostProcessing
Failed
```

Reserved for C010:

```text
QualityChecking
DeliveryReady
QaFailed
```

Hard invariant:

```text
NarrationRequired || OverlaysRequired
    => C004Fallback can never be current/openable.
```

# OPEN FINAL CONTRACT

The one Goal Center action calls:

```text
GoalVideoContinuationViewModel.OpenFinalVideoAsync()
    ->
IPostProductionDeliveryObserver.OpenCurrentAsync()
```

Immediately before shell launch:

1. snapshot current candidate under lock
2. require current job/candidate identity match
3. require an openable phase
4. enforce semantic kind rule again
5. enforce exact C004 or C009 managed path
6. reject reparse/link escape
7. require ordinary output + manifest
8. recheck output bytes
9. recompute output SHA-256
10. recheck manifest bytes
11. recompute manifest SHA-256
12. only then call `IFinalVideoLauncher.Open(exactPath)`

Open never:

- searches for a file
- selects newest artifact
- accepts UI/Core arbitrary path
- creates/recomposes a missing master
- silently falls back to C004
- publishes/uploads anything

If any verification fails:

```text
return false
CanOpen = false
no launcher call
```

# TESTS

Required minimum suites:

1. four narration/overlay selection modes
2. Core-plan cross-lineage rejection
3. exact C009A `MasterCompositionResult` shape enforcement
4. C004 forbidden in every post-production-required failure case
5. durable restart with empty coordinator memory
6. C004 exact managed-path candidate validation
7. C009 exact `MasterPathPolicy` candidate validation
8. output/manifest tamper-at-click rejection
9. reparse/path-escape rejection
10. async open/UI behavior
11. repeated Observe single-flight behavior
12. stale job completion isolation
13. C004/C007B/C008B/C009A/C009B regression
14. Desktop Release build

# BLOCKERS

Only one code-start blocker remains:

**C009B must finish, land, and pass its real Windows mux acceptance.**

Reason:

`ControlCenterSession` must construct C009A's `PostProductionMasterCompositorService` with the actual landed `IMasterVideoComposer`.

C009C must not guess that concrete composer type while C009B is still in flight.

No other architecture blocker remains.

C010 does not block C009C; it only blocks future QA-enforced `QualityChecking / DeliveryReady / QaFailed` behavior.
