# Maotai Interactive Pet Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, attractive, fail-soft Maotai mascot component to the existing native WPF application without changing Core/Worker/task execution behavior.

**Architecture:** Add one isolated WPF `UserControl` plus a tiny presentation policy. The control only renders mascot state, reacts to pointer/click, and raises host events for existing actions; it never calls Core, Worker, network, queue, provider, or persistence services. All animation and hint failures are contained inside the component so the host application remains usable.

**Tech Stack:** .NET 10, WPF, existing smoke-test executable, PNG resources, WPF `Storyboard`/transforms/`DispatcherTimer`; no WebView, Electron, Rive runtime, Spine runtime, or new third-party package.

## Global Constraints

- Stability is the highest priority: mascot failure must not break the host application.
- Keep the existing native WPF product surface and current control/execution boundaries.
- Do not modify Mac Core, Mac Worker, queue facts, task execution, provider behavior, persistence, release/rollback flow, or navigation contracts.
- Keep the first version lightweight: Idle, hover/pointer response, click callout, Working, Success, Away, Bath, Offline.
- Click opens one small callout; action buttons raise events only. The host decides what existing feature to open.
- Automatic hints are local presentation rules only and are rate-limited.
- Use high-quality PNG mascot assets; do not replace the mascot with generic vector/icon artwork.
- Generated code comments must remain consistently aligned and indented.
- TDD: add a failing smoke test before production behavior.

---

### Task 1: Lock the fail-soft component contract

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PetMascotWpfSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Consumes: existing smoke-test runner and WPF STA layout pattern.
- Produces: executable acceptance contract for `PetMascotControl` and its public host-safe events/state surface.

- [ ] **Step 1: Write the failing test**

Create an STA smoke test that resolves `PicotooPet.Desktop.Controls.PetMascot.PetMascotControl` by reflection, verifies it is a WPF element, verifies the `State` property and `NewTaskRequested` / `ProgressRequested` events exist, then measures/arranges the control.

- [ ] **Step 2: Run test to verify it fails**

Run the Windows smoke-test workflow on the isolated branch. Expected: failure because `PetMascotControl` does not exist yet.

- [ ] **Step 3: Do not add production code before RED is observed**

Preserve the failing CI evidence in the draft PR before continuing.

---

### Task 2: Add the isolated mascot presentation model

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotState.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotPromptPolicy.cs`

**Interfaces:**
- Produces: `PetMascotState` enum and deterministic local prompt selection.
- Does not consume: Core, Worker, network, storage, task command APIs.

- [ ] **Step 1: Implement minimal state enum**

States: `Idle`, `Working`, `Success`, `Away`, `Bath`, `Offline`.

- [ ] **Step 2: Implement deterministic prompt policy**

Inputs are only presentation counts/state; outputs are short Chinese strings. No AI/model/network call.

- [ ] **Step 3: Keep policy side-effect free**

No timers, no service access, no persistence, no exception propagation into host business logic.

---

### Task 3: Add WPF control, animations, callout, and visual assets

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml.cs`
- Create binary resources under: `windows/desktop/src/PicotooPet.Desktop/Assets/PetMascot/`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`

**Interfaces:**
- `State` dependency property.
- Presentation count dependency properties: pending review / in progress / completed.
- Events: `NewTaskRequested`, `ProgressRequested`.
- Public method: `ShowInteractionCallout()` for host/test use.

- [ ] **Step 1: Add high-quality PNG resources**

Use existing approved Maotai assets for idle, idle blink, greeting/success, working A/B, away, bath, and offline sleep.

- [ ] **Step 2: Build one compact callout**

Clicking Maotai shows one rounded callout with a short state-aware sentence and at most two buttons: `新建任务` and `看看进度`.

- [ ] **Step 3: Add lightweight motion**

Idle breathing, hover scale/tilt, pointer-follow translation, working frame alternation, success pulse, and offline breathing. No external animation runtime.

- [ ] **Step 4: Add automatic local hint timer**

Rate-limit ordinary hints to a long interval; suppress when not loaded/visible. Timer exceptions are swallowed inside the mascot boundary.

- [ ] **Step 5: Add fail-soft boundary**

Asset/animation/callout failures leave the control inert or hidden instead of throwing into the host page.

---

### Task 4: Verify without changing product wiring

**Files:**
- No homepage integration in this task.

**Interfaces:**
- The result is a reusable WPF control ready for a one-line host insertion after visual review.

- [ ] **Step 1: Run smoke tests**

Expected: all existing smoke tests plus `PetMascotWpfSmokeTests` pass.

- [ ] **Step 2: Run Windows WPF CI**

Expected: successful native Windows build/test workflow on the isolated branch.

- [ ] **Step 3: Compare branch to base**

Confirm no changes under Mac Core, Mac Worker, task execution, queue, provider, persistence, release, rollback, or navigation behavior.

- [ ] **Step 4: Keep PR draft**

Do not merge automatically. Visual placement into `OperatorHomePage` is a later explicit integration step after the component itself is verified.
