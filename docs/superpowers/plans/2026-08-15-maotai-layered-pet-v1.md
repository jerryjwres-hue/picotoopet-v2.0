# Maotai Layered Desktop Pet v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current WPF-drawn vector dog with a premium Q-version Alaskan Malamute mascot named Maotai, rendered from transparent illustrated layers and driven by the existing presentation-only pet state/interaction runtime.

**Architecture:** Keep `AssistantPetPresentation` as the sole business-fact projection and keep the existing same-process WPF pet/floating-window boundary. Replace only the character rendering surface with a Maotai image rig: illustrated base/body/head/limb/prop/effect layers, independent transforms, facial overlays, and short presentation-only sequences. Major state posters are fallbacks and thumbnails only; the live working pet must visibly articulate paws, head, eyes, ears/effects, and return to the current live base state after temporary reactions.

**Tech Stack:** .NET / WPF XAML, C#, WPF `Image`, `Canvas`, `TransformGroup`, `Storyboard`/`DispatcherTimer`, assembly `Resource` PNG assets, existing Windows smoke/CI/release gates.

## Global Constraints

- Character identity is **Maotai**, an Alaskan Malamute; do not label the runtime asset as Husky.
- Preserve the exact five Simple Mode navigation labels: `首页 / 待我审核 / 进行中 / 已完成 / 高级`.
- Do not restructure Core, Worker, task, approval, queue/outbox, result, schema, provider, or persistence behavior.
- Green/orange/gray lamp semantics remain derived from the existing `AssistantPetPresentation.Indicator`.
- Pet animation and expression state is presentation-only and may not expose business write operations.
- No Electron, WebView, remote animation service, remote asset loading, paid inference, or second executable.
- Continuous timers stop when the visual is unloaded/hidden.
- All generated code comments must be visually aligned where adjacent inline comments are used.

---

## File structure locked for this plan

**Create**
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/README.txt` — asset contract, coordinate system, identity and export requirements.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/posters/working.png` — Q-version working fallback/thumbnail.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/posters/working_tired.png` — tired-working fallback/thumbnail.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/posters/working_annoyed.png` — annoyed-working fallback/thumbnail.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/posters/resting.png` — resting fallback/thumbnail.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/posters/offline.png` — sleeping fallback/thumbnail.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/body.png` — torso/back/base fur layer without foreground paws/face overlays.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/head.png` — head/headphones base layer with neutral facial apertures.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/tail.png` — independent fluffy tail layer.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/paw_left.png` — independent left forepaw.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/paw_right.png` — independent right forepaw.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/laptop.png` — independent silver laptop prop.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/rig/drink.png` — optional orange drink prop.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/eyes_open.png` — neutral open-eye overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/eyes_half.png` — tired half-lidded overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/eyes_closed.png` — blink/sleep overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/brows_focused.png` — focused brow overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/brows_annoyed.png` — playful frustrated brow overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/mouth_happy.png` — happy/tongue mouth overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/mouth_tired.png` — tired/yawn mouth overlay.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai/V1/face/mouth_annoyed.png` — small pout overlay.
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetRig.cs` — typed pack-URI catalog and rig geometry constants.
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorSequenceController.cs` — bounded multi-step presentation sequences and current-base-state return contract.
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs` — v1.3 asset/rig/sequence/business-boundary regression contract.

**Modify**
- `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj` — include Maotai PNG assets as WPF `Resource` items.
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml` — replace vector dog primitives with layered Q-version Maotai `Image` elements while preserving status chrome.
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs` — drive image transforms/facial overlays and interaction priority.
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorController.cs` — add v1.3 playful/tired/annoyed work micro-actions without changing business mode.
- `windows/desktop/src/PicotooPet.Desktop/Views/FloatingPetWindow.xaml` — keep the same rig in floating mode and preserve tool affordances.
- `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml` — replace old decorative mascot resource with Maotai poster asset.
- `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/README.txt` — mark legacy Husky assets as compatibility-only and Maotai as the active mascot line.

---

### Task 1: Freeze the v1.3 Maotai rig contract with RED smoke tests

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs`

**Interfaces:**
- Consumes: existing `ShellViewModel`, `AssistantPetPanel`, `AssistantPetPresentation`.
- Produces: required runtime type names `MaotaiPetRig`, `PetBehaviorSequenceController`, `PetBehaviorSequence`, `PetSequenceStep` and required named WPF fields.

- [ ] **Step 1: Write the failing v1.3 smoke contract**

```csharp
using System.Reflection;
using System.Runtime.CompilerServices;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class InteractivePetV13SmokeTests
{
    [ModuleInitializer]
    public static void Initialize()
    {
        var assembly       = typeof(ShellViewModel).Assembly;
        var rigType        = assembly.GetType("PicotooPet.Desktop.Views.Controls.MaotaiPetRig");
        var sequenceType   = assembly.GetType("PicotooPet.Desktop.Views.Controls.PetBehaviorSequenceController");
        var panelType      = assembly.GetType("PicotooPet.Desktop.Views.Controls.AssistantPetPanel");

        SmokeAssert.True(rigType is not null, "v1.3 必须提供 MaotaiPetRig");
        SmokeAssert.True(sequenceType is not null, "v1.3 必须提供 PetBehaviorSequenceController");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        foreach (var field in new[]
                 {
                     "MaotaiBody",
                     "MaotaiHead",
                     "MaotaiTail",
                     "LeftPaw",
                     "RightPaw",
                     "FaceEyes",
                     "FaceBrows",
                     "FaceMouth",
                 })
        {
            SmokeAssert.True(
                panelType!.GetField(field, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public) is not null,
                $"v1.3 Q版分层桌宠缺少 {field}");
        }

        foreach (var forbidden in new[] { "Approve", "Reject", "CreateTask", "CancelTask", "Save", "Connect" })
        {
            var exposed = sequenceType!
                .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Any(method => method.Name.Contains(forbidden, StringComparison.OrdinalIgnoreCase));
            SmokeAssert.True(!exposed, $"桌宠序列控制器不得暴露业务写入方法 {forbidden}");
        }
    }
}
```

- [ ] **Step 2: Run the smoke suite and verify RED**

Run:

```powershell
 dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj
```

Expected: FAIL because `MaotaiPetRig` and `PetBehaviorSequenceController` do not yet exist.

- [ ] **Step 3: Commit the RED test**

```bash
git add windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs
git commit -m "test: freeze Maotai layered pet v1.3 contract"
```

---

### Task 2: Add the Maotai asset package and typed rig catalog

**Files:**
- Create: all `Assets/Pet/Maotai/V1/**` files listed in the file structure.
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetRig.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/README.txt`

**Interfaces:**
- Produces: `MaotaiPetRig` static pack URIs and coordinate constants used by XAML/code-behind.

- [ ] **Step 1: Export the approved Q-version Maotai poster and rig assets**

Use transparent PNG, sRGB, identical 1254x1254 authoring canvas for source exports, with no baked UI/card background. Normalize each rig part to the same canvas origin so WPF can overlay it without per-image guesswork.

- [ ] **Step 2: Add a typed catalog**

```csharp
namespace PicotooPet.Desktop.Views.Controls;

internal static class MaotaiPetRig
{
    private const string Root = "/Picotoo Pet AI;component/Assets/Pet/Maotai/V1";

    public static string Body          => $"{Root}/rig/body.png";
    public static string Head          => $"{Root}/rig/head.png";
    public static string Tail          => $"{Root}/rig/tail.png";
    public static string LeftPaw       => $"{Root}/rig/paw_left.png";
    public static string RightPaw      => $"{Root}/rig/paw_right.png";
    public static string Laptop        => $"{Root}/rig/laptop.png";
    public static string Drink         => $"{Root}/rig/drink.png";
    public static string EyesOpen      => $"{Root}/face/eyes_open.png";
    public static string EyesHalf      => $"{Root}/face/eyes_half.png";
    public static string EyesClosed    => $"{Root}/face/eyes_closed.png";
    public static string BrowsFocused  => $"{Root}/face/brows_focused.png";
    public static string BrowsAnnoyed  => $"{Root}/face/brows_annoyed.png";
    public static string MouthHappy    => $"{Root}/face/mouth_happy.png";
    public static string MouthTired    => $"{Root}/face/mouth_tired.png";
    public static string MouthAnnoyed  => $"{Root}/face/mouth_annoyed.png";
}
```

- [ ] **Step 3: Mark the PNG tree as WPF resources**

Ensure the project includes `Assets/Pet/Maotai/V1/**/*.png` as `Resource`; do not add runtime file-system lookup.

- [ ] **Step 4: Run build to catch invalid pack URIs/resources**

Run:

```powershell
dotnet build windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj -warnaserror
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Maotai windows/desktop/src/PicotooPet.Desktop/Assets/Pet/README.txt windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetRig.cs windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj
git commit -m "feat: add Maotai Q-version pet rig assets"
```

---

### Task 3: Replace the vector dog with the layered Q-version renderer

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs`

**Interfaces:**
- Consumes: `MaotaiPetRig` resource paths and existing `Presentation` dependency property.
- Produces: independent WPF transforms for body/head/tail/paws and face overlays.

- [ ] **Step 1: Replace vector fur primitives with image layers**

The live stage must contain named `Image` fields `MaotaiTail`, `MaotaiBody`, `MaotaiHead`, `LeftPaw`, `RightPaw`, `FaceEyes`, `FaceBrows`, and `FaceMouth`. Preserve `PetMotionLayer`, `PetScale`, `PetRotate`, `PetTranslate`, status text, status lamp, and interaction event bindings.

- [ ] **Step 2: Give each articulated part an independent transform**

Example pattern:

```xml
<Image x:Name="RightPaw"
       Source="/Picotoo Pet AI;component/Assets/Pet/Maotai/V1/rig/paw_right.png"
       RenderTransformOrigin="0.52,0.72">
  <Image.RenderTransform>
    <TransformGroup>
      <RotateTransform x:Name="RightPawRotate" Angle="0" />
      <TranslateTransform x:Name="RightPawTranslate" X="0" Y="0" />
    </TransformGroup>
  </Image.RenderTransform>
</Image>
```

- [ ] **Step 3: Update code-behind animation targets**

Remove shape-specific assumptions (`Ellipse.Fill`, vector mouth path mutation, etc.). Animation functions operate on transforms/opacity/source selection only.

- [ ] **Step 4: Preserve fail-closed fallback**

If an optional facial overlay fails to load, keep `MaotaiHead` visible and retain readable status text/lamp; do not throw into Shell business/navigation flow.

- [ ] **Step 5: Run v1.3 smoke + WPF build**

Run:

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj
dotnet build windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj -warnaserror
```

Expected: rig-field smoke checks PASS and build PASS.

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs
git commit -m "feat: render Maotai from articulated Q-version layers"
```

---

### Task 4: Add working, tired-working and annoyed-working presentation sequences

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorSequenceController.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorController.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs`

**Interfaces:**
- Produces: `PetBehaviorSequence NextSequence(AssistantPetMode mode, PetEmotion emotion)` and bounded steps consumed by `AssistantPetPanel`.

- [ ] **Step 1: Extend RED tests for sequence names and bounded return behavior**

Require sequence identifiers `WorkingType`, `WorkingTired`, `WorkingAnnoyed`, `Blink`, `HeadPat`, `PawHighFive`, `RestBubble`, `OfflineBreath` and a `ReturnsToLatestBaseState` contract flag/property.

- [ ] **Step 2: Implement sequence records/controller**

```csharp
internal sealed record PetSequenceStep(
    TimeSpan Duration,
    double HeadAngle,
    double LeftPawY,
    double RightPawY,
    string EyesKey,
    string BrowsKey,
    string MouthKey);

internal sealed record PetBehaviorSequence(
    string Name,
    IReadOnlyList<PetSequenceStep> Steps,
    bool ReturnsToLatestBaseState);
```

- [ ] **Step 3: Implement actual typing articulation**

`WorkingType` alternates left/right paw Y offsets and small rotations; the head performs low-amplitude screen-check movement; eye overlay blinks independently. The laptop remains static except for optional <=1px visual feedback; never fake task progress.

- [ ] **Step 4: Implement tired-working variation**

Use `eyes_half.png`, `mouth_tired.png`, lowered head, slower paw cadence and occasional yawn. This is a temporary cosmetic sequence only; status remains `Working` and the lamp remains green.

- [ ] **Step 5: Implement annoyed-working variation**

Use `brows_annoyed.png`, `mouth_annoyed.png`, faster bounded paw cadence and a short stress glyph/effect. It is playful presentation, never an error/task status.

- [ ] **Step 6: Ensure user interaction priority**

Pointer capture/head pat/high-five/drag interrupts random sequence playback. On completion or interruption, query the latest `Presentation.Mode` and return there rather than caching the prior base mode.

- [ ] **Step 7: Run tests/build and commit**

Run the smoke suite and warnings-as-errors build; both must PASS.

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorSequenceController.cs windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorController.cs windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs
git commit -m "feat: add Maotai work emotion sequences"
```

---

### Task 5: Preserve resting/offline scenes while keeping live articulation

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs`

**Interfaces:**
- Consumes: current `AssistantPetMode.Resting` and `AssistantPetMode.Offline`.

- [ ] **Step 1: Resting scene**

Use the Q-version Maotai bath poster as a fallback/major pose, but keep bubbles/duck/effects as independent WPF layers so they move separately. Add periodic blink/wink if the face overlay is active.

- [ ] **Step 2: Offline scene**

Use the Q-version sleeping Maotai poster/base; apply slow breathing scale/translate to the body stage and animate `Zzz` independently. Motion frequency is lower than Resting/Working.

- [ ] **Step 3: Verify status truth remains independent of decorative scene**

Green/orange/gray lamp and title/detail continue to come only from `Presentation`; scene animations cannot write them.

- [ ] **Step 4: Run smoke/build and commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs
git commit -m "feat: add Q-version Maotai rest and sleep scenes"
```

---

### Task 6: Apply the Maotai identity consistently to floating mode and Home

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/FloatingPetWindow.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml`

**Interfaces:**
- Consumes: same `AssistantPetPanel` and poster assets; no new view model.

- [ ] **Step 1: Floating mode**

Confirm the floating window hosts the exact same layered `AssistantPetPanel`; do not create a second renderer/session. Tune available size so the Q-version art is not clipped at 100%/115%/130% presets.

- [ ] **Step 2: Home hero**

Replace the legacy Husky decorative `Image Source` with the Maotai working poster. This Home image remains decorative and does not duplicate the live pet controller.

- [ ] **Step 3: Run WPF smoke/build and commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/FloatingPetWindow.xaml windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml
git commit -m "feat: apply Maotai identity across pet surfaces"
```

---

### Task 7: Performance, unload safety and interaction regression pass

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs`

**Interfaces:**
- Verifies: timers suspend on unload/visibility loss, interaction priority, no business writes.

- [ ] **Step 1: Add smoke assertions for timer/visibility hooks and business-write absence**

Require the existing `PetSurface_IsVisibleChanged` and `PetSurface_Unloaded` lifecycle hooks and sequence controller write-method ban.

- [ ] **Step 2: Ensure only low-frequency behavior scheduling remains continuous**

Do not introduce frame-rate polling. WPF animations/transforms run only for active sequences; pointer tracking runs only while pointer is inside the pet surface.

- [ ] **Step 3: Run all Windows desktop smoke tests and warnings-as-errors build**

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj
dotnet build windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj -warnaserror
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml.cs windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs
git commit -m "test: harden Maotai pet lifecycle boundaries"
```

---

### Task 8: Full Windows CI / release acceptance package

**Files:**
- Update PR description/evidence only after successful runs.

**Interfaces:**
- Produces: v1.3 Windows Prebuilt acceptance artifact and installer ZIP.

- [ ] **Step 1: Run/observe Windows Control Center Slice D CI for the final head**

Expected mandatory PASS steps:
- contract/security tests
- exact .NET SDK setup
- legacy Task Center regression reproduction
- WPF smoke including v1.3 Maotai contract
- warnings-as-errors build
- published Control Center self-test

- [ ] **Step 2: Run/observe Phase 2.3 Slice D Windows Prebuilt Release**

Expected mandatory PASS steps:
- release analyzer / goal-integrity contracts
- build / analyze / publish / self-test
- native WPF delivery invariants
- installer project-goal validation
- install / upgrade / recovery / rollback lifecycle
- formal artifact upload

- [ ] **Step 3: Download the successful formal artifact and provide a user-facing v1.3 installer ZIP**

Do not claim zero bugs. Report the exact final head SHA, CI run numbers, release run number, artifact digest, and keep PR #35 Draft/unmerged for real-machine visual acceptance.

---

## Plan self-review

- Spec coverage: Q-version identity, layered live movement, working/tired/annoyed expressions, resting/offline states, floating reuse, UI mascot consistency, failure isolation, performance, and Windows release gates all have explicit tasks.
- Placeholder scan: no TBD/TODO/"implement later" placeholders.
- Type consistency: `MaotaiPetRig`, `PetBehaviorSequenceController`, `PetBehaviorSequence`, `PetSequenceStep` names are consistent across tasks and smoke contract.
- Scope: this plan intentionally isolates the Maotai renderer/behavior subproject from the broader v1.3 visual-polish work; the rest of the shell polish can continue after this plan reaches a green installable checkpoint.
