# Interactive Pet v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fact-driven, locally animated husky pet to the existing Simple Mode WPF sidebar without changing PicotooPet control-plane boundaries.

**Architecture:** A pure `AssistantPetPresentation` projection converts the existing `ControlCenterSessionSnapshot` into one visual mode. `ShellViewModel` exposes that global presentation. `InteractivePetPanel` renders local transparent PNG resources and applies bounded WPF transforms for breathing, pointer-follow, click bounce, state transition, and error shake.

**Tech Stack:** .NET 10, native WPF/XAML, existing zero-third-party smoke-test harness, GitHub Actions `windows-2025` gate.

## Global Constraints

- Formal Windows surface remains native WPF `Picotoo Pet AI.exe`.
- Mac Core + SQLite Queue/Outbox remains fact source.
- Pet presentation never mutates task, approval, queue, Worker, or connection state.
- No Provider call, upload, paid inference, project scan, log-body capture, token capture, or user-file enumeration.
- Keep the frozen five Simple Mode navigation entries unchanged.
- Use TDD: failing smoke assertion before production behavior.

---

### Task 1: Pet state projection

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/ViewModels/AssistantPetPresentation.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetSmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Consumes: `ControlCenterSessionSnapshot`.
- Produces: `AssistantPetMode` and `AssistantPetPresentation.FromSnapshot(ControlCenterSessionSnapshot)`.

- [ ] **Step 1: Write failing smoke tests** for Error, Offline, Working, Waiting, Resting and Working-over-Waiting priority.
- [ ] **Step 2: Trigger the Draft PR Windows CI and confirm RED** because `AssistantPetPresentation` does not exist.
- [ ] **Step 3: Implement the minimal deterministic projection** with no persistence or commands.
- [ ] **Step 4: Re-run Windows CI and confirm the state-projection assertions pass.**
- [ ] **Step 5: Commit** with `feat: add fact-driven assistant pet state`.

### Task 2: Global Shell binding

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetSmokeTests.cs`

**Interfaces:**
- Consumes: `AssistantPetPresentation.FromSnapshot`.
- Produces: `ShellViewModel.PetPresentation` updated whenever a session snapshot is accepted.

- [ ] **Step 1: Add a failing assertion** that smoke Shell exposes a deterministic offline pet and runtime snapshot refresh recalculates presentation.
- [ ] **Step 2: Confirm RED in Windows CI.**
- [ ] **Step 3: Add `PetPresentation` initialization and refresh inside existing snapshot flow.**
- [ ] **Step 4: Confirm GREEN in Windows CI.**
- [ ] **Step 5: Commit** with `feat: bind assistant pet to shell facts`.

### Task 3: Native interactive WPF control

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/InteractivePetPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/InteractivePetPanel.xaml.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetSmokeTests.cs`

**Interfaces:**
- Consumes: `ShellViewModel.PetPresentation`.
- Produces: sidebar visual only; no session or task methods.

- [ ] **Step 1: Add a failing STA layout assertion** that `InteractivePetPanel` measures/arranges and that `ShellWindow.xaml` contains the control while the five nav buttons remain unchanged.
- [ ] **Step 2: Confirm RED in Windows CI.**
- [ ] **Step 3: Add the UserControl** with state label, detail copy, image host, transforms, and local fallback copy.
- [ ] **Step 4: Add bounded motion**: breathing, pointer tilt, click bounce, state fade, unload cleanup, and error shake.
- [ ] **Step 5: Place the control below navigation in the existing 220px sidebar without introducing a new navigation route.**
- [ ] **Step 6: Confirm GREEN in Windows CI and warnings-as-errors build.**
- [ ] **Step 7: Commit** with `feat: add native interactive pet panel`.

### Task 4: Local husky assets

**Files:**
- Create binary resources under `windows/desktop/src/PicotooPet.Desktop/Assets/Pet/Husky/V1/`:
  - `idle.png`
  - `working.png`
  - `resting.png`
  - `offline.png`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetSmokeTests.cs`

**Interfaces:**
- `AssistantPetPresentation.AssetKey` maps to the four local resources. Waiting reuses `idle.png`; Error uses `idle.png` plus non-playful error motion.

- [ ] **Step 1: Add a failing resource-presence assertion** for all four pack URIs.
- [ ] **Step 2: Confirm RED in Windows CI.**
- [ ] **Step 3: Commit optimized transparent PNG assets and explicit WPF `Resource` items.**
- [ ] **Step 4: Confirm all resources resolve in STA and GREEN in Windows CI.**
- [ ] **Step 5: Commit** with `feat: add husky pet visual pack v1`.

### Task 5: Full verification and PR evidence

**Files:**
- No production changes unless verification finds a defect.

- [ ] **Step 1: Run the Draft PR Windows Control Center CI.**
- [ ] **Step 2: Confirm contract/security tests, WPF smoke suite, warnings-as-errors build, and self-test all pass.**
- [ ] **Step 3: Review PR diff for accidental control-plane changes, remote asset calls, or navigation changes.**
- [ ] **Step 4: Update the Draft PR body with exact verification evidence and keep it unmerged for user review.**
