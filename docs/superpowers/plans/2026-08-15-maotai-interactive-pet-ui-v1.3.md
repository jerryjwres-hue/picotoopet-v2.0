# Maotai Interactive Pet + Simple Mode UI v1.3 Implementation Plan

> **Execution:** implement against the existing Draft branch only; keep `feature/operator-simple-mode-2.3.26.1` unchanged until visual acceptance.

**Goal:** Replace the visible WPF vector placeholder with the Q-version Alaskan Malamute named 茅台, keep true interactive/articulated behavior, and continue the Simple Mode UI polish without changing Core/Worker/task/approval authority.

**Architecture:** Keep `AssistantPetPresentation` as the truthful base-state projection. Add a raster illustration rig above it: one Q-version canvas supplies the working artwork while clipped WPF `Image` layers independently drive head, paws and tail. Temporary tired/annoyed artwork can replace the working raster without changing the real base mode. High-detail acceptance assets load only from a fixed application-owned LocalAppData UI directory and fall back to bundled resources when missing/corrupt, so CI and normal startup remain safe.

**Tech Stack:** .NET WPF, XAML, `ImageSource`/`BitmapImage`, `TranslateTransform`/`RotateTransform`/`ScaleTransform`, `DispatcherTimer`, existing Windows smoke/CI/release gates.

---

### Task 1: Freeze the Q-version Maotai contract

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/InteractivePetV13SmokeTests.cs`

**Steps:**
1. Add a RED smoke contract requiring `MaotaiPetRig`, raster-layer fields, behavior sequence types, and absence of business-write APIs.
2. Run the Windows WPF smoke gate and confirm the failure is caused by the missing v1.3 presentation types.

### Task 2: Add the presentation-only behavior sequence layer

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/PetBehaviorSequenceController.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetRig.cs`

**Steps:**
1. Add bounded work/rest/wait/offline/error sequences.
2. Keep sequence outputs presentation-only and require return to the latest real base state.
3. Add fixed logical asset keys for working/tired/annoyed/rest/offline artwork.

### Task 3: Replace the visible vector placeholder with the Maotai raster rig

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.Maotai.cs`
- Create: `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetAssetLoader.cs`

**Steps:**
1. Keep legacy named WPF vector controls invisible only for v1.2 compatibility/tests.
2. Make Q-version raster `Image` layers the only visible dog artwork.
3. Use one same-canvas working raster plus clipped overlays for independent head, left-paw, right-paw and tail transforms.
4. Drive typing cadence with alternating paw transforms, subtle head/screen attention and tail energy.
5. Use temporary tired/annoyed raster swaps for obvious expression changes while keeping `AssistantPetMode.Working` unchanged.
6. Make pointer-follow, head pat, paw wave, drag and celebration affect the visible raster rig.
7. Stop all extra animation timers when hidden/unloaded.

### Task 4: Add safe high-detail acceptance assets

**Runtime contract:**
- `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v1\working.png`
- `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v1\working_tired.png`
- `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v1\working_annoyed.png`
- `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v1\resting.png`
- `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v1\offline.png`

**Steps:**
1. Load only the five fixed filenames above; do not enumerate arbitrary user files.
2. Decode with `BitmapCacheOption.OnLoad` and freeze the resulting image sources.
3. If an asset is missing, inaccessible or invalid, fall back to bundled resources and keep Shell operational.
4. Package the high-detail Q-version artwork alongside the acceptance installer and copy it into the fixed UI asset directory after a successful install.

### Task 5: Continue Simple Mode visual polish around the new pet

**Files:**
- Modify as needed: `ShellWindow.xaml`, `OperatorHomePage.xaml`, `OperatorReviewPage.xaml`, `OperatorTaskListPage.xaml`

**Steps:**
1. Preserve the frozen five navigation labels.
2. Keep green/orange/gray status semantics derived from `PetPresentation.Indicator`.
3. Make the left pet stage visually dominant while keeping text status readable.
4. Re-check 125%/150% DPI and minimum-window behavior.
5. Do not add new business commands or fake task/resource values.

### Task 6: Verify and package

**Steps:**
1. Run contract/security tests.
2. Run the legacy Task Center regression reproduction.
3. Run WPF smoke including the v1.3 Maotai contract.
4. Build WPF with warnings as errors.
5. Run the published Control Center self-test.
6. Run the formal Windows Prebuilt Release gate including install/upgrade/recovery/rollback lifecycle.
7. Download the successful artifact.
8. Build one user-facing acceptance ZIP containing the formal installer plus the five high-detail Maotai Q-version assets and the asset-install wrapper.
9. Keep PR #35 Draft/unmerged until real-machine visual acceptance completes.
