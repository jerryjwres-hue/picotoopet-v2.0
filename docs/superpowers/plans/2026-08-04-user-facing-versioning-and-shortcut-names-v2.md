# PicotooPet 用户可见版本号与快捷方式命名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立唯一的四段式产品版本 `2.3.6.1`，让 Mac Core、Mac Worker、Windows WPF、三平台安装包及 INSTALL / VERIFY / ROLLBACK 报告保持一致，并让 Windows 三处快捷方式只保留当前版本且能够精确回滚。

**Architecture:** `src/picotoopet_core/product-version.txt` 是唯一版本值源。Python 通过 package resource 读取；Mac 构建器把同一文件复制进 Core/Worker 包；Windows csproj 把同一文件复制到 build/publish 输出，WPF 运行时从 `AppContext.BaseDirectory` 读取。`product_version` 表示用户版本，现有 `version`、Git SHA、run ID、workflow ref 继续表示内部构建和溯源。Windows 快捷方式使用受管名称白名单与完整 COM 属性快照，安装、失败恢复和回滚不靠猜测名称。

**Tech Stack:** Python 3.12、FastAPI、pytest、Bash、macOS LaunchAgent、.NET 10、WPF、C#、Windows PowerShell 5.1、PowerShell 7、GitHub Actions。

## Global Constraints

- 当前用户版本固定为 `2.3.6.1`。
- 同一功能修复递增第四段；下一项正常功能递增第三段并把第四段重置为 `1`。
- 唯一版本值源是 `src/picotoopet_core/product-version.txt`。
- Windows 左上角精确显示 `Control Center · v2.3.6.1`。
- Windows 窗口标题精确显示 `Picotoo Pet AI 2.3.6.1`。
- 桌面、开始菜单、启动项各只保留 `Picotoo Pet AI 2.3.6.1.lnk`。
- 只管理三个受管目录中名称为 `Picotoo Pet AI.lnk` 或匹配 `Picotoo Pet AI <四段版本>.lnk` 的快捷方式；不扫描其他目录。
- 快捷方式回滚恢复名称、目标、参数、工作目录、图标和描述。
- `version` 保留为内部唯一构建 ID；`product_version` 表示用户版本。
- 不改变 Mac Core + SQLite Queue/Outbox 事实源、Mac Worker 执行边界或 Windows 原生 WPF 产品形态。
- 不在用户 Windows 或 Mac 上编译。
- PR #8 始终保持 Draft、open、unmerged；不修改或合并 `main`。
- 本文件是实施权威计划，取代同目录下无 `-v2` 后缀的初稿。

---

## File Structure

### Create

- `src/picotoopet_core/product-version.txt`：唯一版本值。
- `src/picotoopet_core/versioning.py`：Python 版本读取与格式验证。
- `tests/unit/test_product_version.py`：版本源单元测试。
- `tests/integration/api/test_product_version_api.py`：真实 health.version 回归。
- `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs`：WPF 运行时版本提供器。
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`：STA WPF 版本绑定测试。

### Modify

- `pyproject.toml`
- `src/picotoopet_core/__init__.py`
- `deploy/macos/phase23/lib.sh`
- `deploy/macos/phase23/INSTALL_MAC_CORE_SLICE_B.command`
- `deploy/macos/phase23/VERIFY_MAC_CORE_SLICE_B.command`
- `scripts/mac/phase23/Build-MacCoreSliceBDelta.sh`
- `scripts/mac/phase23/Test-MacCoreSliceBDelta.sh`
- `scripts/mac/phase23/Test-MacCoreSliceBFixture.sh`
- `deploy/macos/phase23-worker/worker-lib.sh`
- `deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command`
- `deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command`
- `scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh`
- `scripts/mac/phase23-worker/Test-MacWorkerSliceC.sh`
- `scripts/mac/phase23-worker/Test-MacWorkerSliceCFixture.sh`
- `tests/contract/test_phase23_mac_delta_source.py`
- `tests/contract/test_phase23_worker_delivery.py`
- `tests/security/test_phase23_mac_delta_security.py`
- `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- `windows/desktop/release/Phase2Prebuilt.Common.ps1`
- `windows/desktop/release/Install-Phase2Prebuilt.ps1`
- `windows/desktop/release/Verify-Phase2Prebuilt.ps1`
- `windows/desktop/release/Rollback-Phase2Prebuilt.ps1`
- `windows/desktop/scripts/Test-Phase2WindowsRelease.ps1`
- `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`
- `contracts/release/project-goal-invariants.json`
- `scripts/stamp_windows_goal_integrity.py`
- `scripts/verify_project_goal_integrity.py`
- `tests/contract/test_phase23_windows_source.py`
- `tests/contract/test_project_goal_integrity.py`
- `tests/contract/test_windows_goal_integrity_stamper.py`
- `tests/release/test_windows_prebuilt_delivery.py`
- `tests/release/test_windows_goal_integrity_release_contract.py`
- `.github/workflows/macos-core-slice-b-ci.yml`
- `.github/workflows/macos-worker-slice-c-ci.yml`
- `.github/workflows/windows-control-center-ci.yml`
- `.github/workflows/windows-phase2-release.yml`

---

### Task 1: Canonical Product Version Resource

**Files:**
- Create: `src/picotoopet_core/product-version.txt`
- Create: `src/picotoopet_core/versioning.py`
- Create: `tests/unit/test_product_version.py`
- Modify: `src/picotoopet_core/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `parse_product_version(raw: str) -> str`
- Produces: `PRODUCT_VERSION: str`
- Produces: `picotoopet_core.__version__ == PRODUCT_VERSION`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from picotoopet_core import __version__
from picotoopet_core.versioning import PRODUCT_VERSION, parse_product_version

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "src" / "picotoopet_core" / "product-version.txt"


def test_canonical_product_version_is_2361() -> None:
    assert VERSION_FILE.read_text(encoding="utf-8").strip() == "2.3.6.1"
    assert PRODUCT_VERSION == "2.3.6.1"
    assert __version__ == PRODUCT_VERSION


@pytest.mark.parametrize("value", ["2.3.6", "2.3.6.1.0", "v2.3.6.1", "2.3.x.1", ""])
def test_rejects_non_four_part_product_versions(value: str) -> None:
    with pytest.raises(ValueError, match="四段"):
        parse_product_version(value)
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_product_version.py -q
```

Expected: FAIL because `versioning.py` and `product-version.txt` do not exist or `__version__` is still `2.3.0-slice-c`.

- [ ] **Step 3: Implement the canonical resource**

`product-version.txt` contains exactly:

```text
2.3.6.1
```

`versioning.py`:

```python
from __future__ import annotations

import re
from importlib.resources import files

_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$")


def parse_product_version(raw: str) -> str:
    value = raw.strip()
    if not _PATTERN.fullmatch(value):
        raise ValueError(f"产品版本必须是四段数字：{raw!r}")
    return value


PRODUCT_VERSION = parse_product_version(
    files("picotoopet_core").joinpath("product-version.txt").read_text(encoding="utf-8")
)
```

`__init__.py`:

```python
"""Picotoo Pet V2 Mac Core。"""

from .versioning import PRODUCT_VERSION

__version__ = PRODUCT_VERSION
```

Add package data without replacing any existing package-data entries:

```toml
[tool.setuptools.package-data]
picotoopet_core = ["product-version.txt"]
```

- [ ] **Step 4: Run GREEN and inspect the wheel**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_product_version.py -q
python -m pip install --disable-pip-version-check build
python -m build --wheel
python -c "import pathlib, zipfile; p=next(pathlib.Path('dist').glob('*.whl')); z=zipfile.ZipFile(p); assert any(n.endswith('picotoopet_core/product-version.txt') for n in z.namelist())"
```

Expected: PASS; the wheel contains `picotoopet_core/product-version.txt`.

- [ ] **Step 5: Commit**

```bash
git add src/picotoopet_core/product-version.txt src/picotoopet_core/versioning.py src/picotoopet_core/__init__.py pyproject.toml tests/unit/test_product_version.py
git commit -m "feat: add canonical product version 2.3.6.1"
```

---

### Task 2: Mac Core Exact Running Version

**Files:**
- Create: `tests/integration/api/test_product_version_api.py`
- Modify: `deploy/macos/phase23/lib.sh`
- Modify: `deploy/macos/phase23/INSTALL_MAC_CORE_SLICE_B.command`
- Modify: `deploy/macos/phase23/VERIFY_MAC_CORE_SLICE_B.command`
- Modify: `scripts/mac/phase23/Build-MacCoreSliceBDelta.sh`
- Modify: `scripts/mac/phase23/Test-MacCoreSliceBDelta.sh`
- Modify: `scripts/mac/phase23/Test-MacCoreSliceBFixture.sh`
- Modify: `tests/contract/test_phase23_mac_delta_source.py`
- Modify: `tests/security/test_phase23_mac_delta_security.py`

**Interfaces:**
- Produces: `/api/v1/health.version == "2.3.6.1"`
- Produces: Core Manifest/report `product_version`
- Produces: VERIFY failure with explicit expected/actual mismatch

- [ ] **Step 1: Write failing API and delivery tests**

```python
from fastapi.testclient import TestClient

from picotoopet_core import __version__
from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def test_health_returns_canonical_product_version(tmp_path) -> None:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["version"] == __version__ == "2.3.6.1"
```

```python
def test_core_verify_rejects_wrong_running_version() -> None:
    verify = (DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command").read_text(encoding="utf-8")
    assert 'health.get("version") != expected_product_version' in verify
    assert "expected=" in verify
    assert "actual=" in verify
```

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python -m pytest \
  tests/integration/api/test_product_version_api.py \
  tests/contract/test_phase23_mac_delta_source.py \
  tests/security/test_phase23_mac_delta_security.py -q
```

Expected: old health version or missing VERIFY check causes failure.

- [ ] **Step 3: Add package version reading and report fields**

In `lib.sh`:

```bash
phase23_product_version() {
  local version_file
  version_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/product-version.txt"
  [[ -f "$version_file" ]] || { echo "missing product-version.txt" >&2; return 1; }
  local value
  value="$(tr -d '\r\n' < "$version_file")"
  [[ "$value" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    echo "invalid product version: $value" >&2
    return 1
  }
  printf '%s\n' "$value"
}
```

The builder copies the canonical file to the package root. INSTALL, VERIFY and report writers pass `product_version` separately from role-specific `runtime_version`.

- [ ] **Step 4: Enforce the live health version**

VERIFY passes `expected_product_version` into its Python check:

```python
health = get("/api/v1/health")
actual = health.get("version")
if actual != expected_product_version:
    raise SystemExit(
        f"Mac Core product version mismatch: expected={expected_product_version!r}, actual={actual!r}"
    )
```

A fixture with actual `2.3.6.0` must fail even when all diagnostic API paths exist.

- [ ] **Step 5: Run focused tests and macOS syntax checks**

```bash
PYTHONPATH=src python -m pytest \
  tests/unit/test_product_version.py \
  tests/integration/api/test_product_version_api.py \
  tests/contract/test_phase23_mac_delta_source.py \
  tests/security/test_phase23_mac_delta_security.py -q
bash -n deploy/macos/phase23/*.command deploy/macos/phase23/lib.sh scripts/mac/phase23/*.sh
```

Expected: PASS; Core reports include `product_version: 2.3.6.1`.

- [ ] **Step 6: Commit**

```bash
git add deploy/macos/phase23 scripts/mac/phase23 tests/integration/api/test_product_version_api.py tests/contract/test_phase23_mac_delta_source.py tests/security/test_phase23_mac_delta_security.py
git commit -m "fix: enforce Mac Core product version 2.3.6.1"
```

---

### Task 3: Mac Worker Active Runtime Version

**Files:**
- Modify: `deploy/macos/phase23-worker/worker-lib.sh`
- Modify: `deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command`
- Modify: `deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command`
- Modify: `scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh`
- Modify: `scripts/mac/phase23-worker/Test-MacWorkerSliceC.sh`
- Modify: `scripts/mac/phase23-worker/Test-MacWorkerSliceCFixture.sh`
- Modify: `tests/contract/test_phase23_worker_delivery.py`

**Interfaces:**
- Produces: `verify_worker_product_version(runtime_root: shell path, expected_product_version: string)`
- Produces: Worker Manifest/report `product_version`
- Preserves: `runtime_version: "2.3.0-slice-d-worker"`
- Preserves: `system.diagnostic_snapshot` and `system.noop`

- [ ] **Step 1: Write the failing contract**

```python
def test_worker_verify_checks_active_runtime_product_version() -> None:
    verify = (DEPLOY / "VERIFY_MAC_WORKER_SLICE_C.command").read_text(encoding="utf-8")
    library = (DEPLOY / "worker-lib.sh").read_text(encoding="utf-8")
    assert "verify_worker_product_version" in verify
    assert "from picotoopet_core import __version__" in library
    assert "expected_product_version" in library
    assert '"product_version"' in library
```

Package structure tests also require top-level `product-version.txt` and Manifest `product_version`.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_worker_delivery.py -q
```

Expected: missing active-runtime check and report field cause failure.

- [ ] **Step 3: Implement active venv verification**

```bash
verify_worker_product_version() {
  local runtime_root="$1"
  local expected_product_version="$2"
  "$runtime_root/current/.venv/bin/python" - "$expected_product_version" <<'PY'
import sys
from picotoopet_core import __version__

expected = sys.argv[1]
if __version__ != expected:
    raise SystemExit(
        f"Mac Worker product version mismatch: expected={expected!r}, actual={__version__!r}"
    )
PY
}
```

VERIFY order:

1. Read and validate package `product-version.txt`.
2. Verify active venv `__version__`.
3. Wait for Worker online state.
4. Verify the two exact task types.
5. Write a report containing `product_version` and existing role fields.

- [ ] **Step 4: Update Worker package construction**

The builder copies the canonical version file, adds it to Manifest hashes/sizes, writes `product_version`, and includes `2.3.6.1` in the tar.gz filename. It must not replace the role identifier `2.3.0-slice-d-worker` used for internal runtime diagnostics.

- [ ] **Step 5: Run GREEN and negative fixture**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_worker_delivery.py -q
bash -n deploy/macos/phase23-worker/*.command deploy/macos/phase23-worker/worker-lib.sh scripts/mac/phase23-worker/*.sh
```

Expected: normal fixture PASS; changing expected package version to `2.3.6.0` causes nonzero VERIFY; task-type contract remains unchanged.

- [ ] **Step 6: Commit**

```bash
git add deploy/macos/phase23-worker scripts/mac/phase23-worker tests/contract/test_phase23_worker_delivery.py
git commit -m "fix: enforce Mac Worker product version 2.3.6.1"
```

---

### Task 4: Windows WPF User-Visible Version Surfaces

**Files:**
- Create: `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs`
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`
- Modify: `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`
- Modify: `tests/contract/test_phase23_windows_source.py`

**Interfaces:**
- Produces: `ProductVersionInfo.Current`
- Produces: `ProductVersionInfo.WindowTitle`
- Produces: `ProductVersionInfo.ControlCenterSubtitle`
- Produces: `ShellViewModel.WindowTitle`
- Produces: `ShellViewModel.ControlCenterSubtitle`

- [ ] **Step 1: Write failing XAML wiring tests**

```python
def test_shell_binds_product_version_surfaces() -> None:
    shell = read("Views/ShellWindow.xaml")
    view_model = read("ViewModels/ShellViewModel.cs")
    assert 'Title="{Binding WindowTitle, Mode=OneWay}"' in shell
    assert 'Text="{Binding ControlCenterSubtitle, Mode=OneWay}"' in shell
    assert "Control Center · Slice B" not in shell
    assert "ProductVersionInfo.WindowTitle" in view_model
    assert "ProductVersionInfo.ControlCenterSubtitle" in view_model
```

- [ ] **Step 2: Write the failing STA WPF test**

```csharp
internal static class ProductVersionWpfSmokeTests
{
    public static void Run()
    {
        var viewModel = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);
        var window = new Window { DataContext = viewModel };
        BindingOperations.SetBinding(
            window,
            Window.TitleProperty,
            new Binding(nameof(ShellViewModel.WindowTitle)) { Mode = BindingMode.OneWay });
        var subtitle = new TextBlock();
        BindingOperations.SetBinding(
            subtitle,
            TextBlock.TextProperty,
            new Binding(nameof(ShellViewModel.ControlCenterSubtitle)) { Mode = BindingMode.OneWay });
        window.Content = subtitle;
        window.Measure(new Size(900, 700));
        window.Arrange(new Rect(0, 0, 900, 700));
        window.UpdateLayout();
        window.Dispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
        SmokeAssert.True(window.Title == "Picotoo Pet AI 2.3.6.1", "窗口标题版本错误");
        SmokeAssert.True(subtitle.Text == "Control Center · v2.3.6.1", "左上角版本错误");
        window.Close();
    }
}
```

`Program.Main` calls `ProductVersionWpfSmokeTests.Run()` before the existing TaskCenter layout test.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_windows_source.py -q
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: missing properties/provider cause failure.

- [ ] **Step 4: Copy the canonical file into every Windows output**

```xml
<Content Include="..\..\..\..\src\picotoopet_core\product-version.txt"
         Link="product-version.txt">
  <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
  <CopyToPublishDirectory>Always</CopyToPublishDirectory>
</Content>
```

- [ ] **Step 5: Implement the fail-closed C# provider**

```csharp
public static class ProductVersionInfo
{
    public const string FileName = "product-version.txt";
    private static readonly Regex Pattern = new(
        "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    public static string Current { get; } = Parse(
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, FileName)));
    public static string WindowTitle => $"Picotoo Pet AI {Current}";
    public static string ControlCenterSubtitle => $"Control Center · v{Current}";

    public static string Parse(string raw)
    {
        var value = raw.Trim();
        return Pattern.IsMatch(value)
            ? value
            : throw new InvalidDataException($"产品版本必须是四段数字：{raw}");
    }
}
```

Expose the two strings through `ShellViewModel`; bind both XAML surfaces OneWay. Add `product_version`, `window_title`, and `control_center_subtitle` to the application self-test report.

- [ ] **Step 6: Run GREEN, warnings-as-errors and published self-test**

```powershell
dotnet run `
  --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj `
  --configuration Release

dotnet build windows/desktop/PicotooPet.Desktop.sln `
  --configuration Release `
  --nologo `
  -warnaserror
```

Expected: product-version STA test PASS; existing real TaskCenter `Measure / Arrange / UpdateLayout` PASS; self-test fields equal `2.3.6.1` strings.

- [ ] **Step 7: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests tests/contract/test_phase23_windows_source.py
git commit -m "feat: show product version 2.3.6.1 in WPF"
```

---

### Task 5: Versioned Windows Shortcut Lifecycle

**Files:**
- Modify: `windows/desktop/release/Phase2Prebuilt.Common.ps1`
- Modify: `windows/desktop/release/Install-Phase2Prebuilt.ps1`
- Modify: `windows/desktop/release/Verify-Phase2Prebuilt.ps1`
- Modify: `windows/desktop/release/Rollback-Phase2Prebuilt.ps1`
- Modify: `windows/desktop/scripts/Test-Phase2WindowsRelease.ps1`
- Modify: `tests/release/test_windows_prebuilt_delivery.py`

**Interfaces:**
- Produces: `Get-PicotooManagedShortcutSnapshot`
- Produces: `Restore-PicotooManagedShortcutSnapshot`
- Produces: `Remove-PicotooManagedShortcuts`
- Produces: `Set-PicotooShortcuts -Executable -ProductVersion`
- Produces: `Assert-PicotooShortcuts -Executable -ProductVersion -RequireNoLegacy`
- Pointer field: `shortcut_state`

- [ ] **Step 1: Write failing static contracts**

```python
def test_versioned_shortcuts_use_snapshots_and_exact_restore() -> None:
    common = read_release("Phase2Prebuilt.Common.ps1")
    install = read_release("Install-Phase2Prebuilt.ps1")
    rollback = read_release("Rollback-Phase2Prebuilt.ps1")
    for required in (
        "Get-PicotooManagedShortcutSnapshot",
        "Restore-PicotooManagedShortcutSnapshot",
        "Remove-PicotooManagedShortcuts",
        "ProductVersion",
        "RequireNoLegacy",
    ):
        assert required in common
    assert "shortcut_state" in install
    assert "shortcut_state" in rollback
```

- [ ] **Step 2: Add failing lifecycle fixtures**

Add `Set-PackageProductVersion` to mutate fixture `product-version.txt`, Manifest `product_version`, file hash and size. Execute these scenarios in both normal and redirected OneDrive desktop fixtures:

1. Seed three unversioned shortcuts with target, arguments, working directory, icon and description.
2. Install fixture product `2.3.5.9`; only `Picotoo Pet AI 2.3.5.9.lnk` remains.
3. Install `2.3.6.1`; only `Picotoo Pet AI 2.3.6.1.lnk` remains.
4. Roll back; exact `2.3.5.9` names and COM properties return.
5. Run an intentional activation failure from the initially seeded state; exact unversioned names and COM properties return.

The helper that changes fixture product version must update the payload entry:

```powershell
$entry.sha256 = (Get-FileHash -LiteralPath $versionFile -Algorithm SHA256).Hash.ToLowerInvariant()
$entry.size_bytes = (Get-Item -LiteralPath $versionFile).Length
$manifest.product_version = $ProductVersion
```

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=src python -m pytest tests/release/test_windows_prebuilt_delivery.py -q
```

On native Windows:

```powershell
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected: old fixed `Picotoo Pet AI.lnk` behavior fails the new contract.

- [ ] **Step 4: Implement the managed-name and snapshot model**

Only this regex is managed:

```powershell
$PicotooManagedShortcutPattern = '^Picotoo Pet AI(?: [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)?\.lnk$'
```

Each snapshot entry contains:

```powershell
[ordered]@{
    location          = "desktop"
    name              = $file.Name
    path              = $file.FullName
    target_path       = [string]$shortcut.TargetPath
    arguments         = [string]$shortcut.Arguments
    working_directory = [string]$shortcut.WorkingDirectory
    icon_location     = [string]$shortcut.IconLocation
    description       = [string]$shortcut.Description
}
```

`Set-PicotooShortcuts` removes all managed names in the three known directories, then creates exactly:

```powershell
$shortcutName = "Picotoo Pet AI $ProductVersion.lnk"
```

`Assert-PicotooShortcuts -RequireNoLegacy` requires one exact shortcut per directory and no other managed names.

- [ ] **Step 5: Wire snapshots into install, failure recovery and rollback**

Before pointer changes:

```powershell
$preActivationShortcutState = Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory
```

Rules:

- If a current pointer exists, attach the actual pre-activation snapshot as that pointer's `shortcut_state` before writing it to `previous_version.json`.
- After creating current shortcuts, capture and store their state in the new current pointer.
- Install failure restores `$preActivationShortcutState` directly.
- Rollback restores `$previous.shortcut_state` directly.
- A historical pointer without `shortcut_state` may use a one-time fallback based on `previous.product_version`; the report writes `shortcut_restore_mode: legacy-pointer-fallback`.
- Every new `2.3.6.1` pointer must have `shortcut_state`; fallback is an error for new pointers.

- [ ] **Step 6: Run GREEN on PowerShell 5.1**

```powershell
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected: normal desktop and redirected desktop pass replacement, exact rollback and intentional-failure recovery; no extra managed shortcuts remain.

- [ ] **Step 7: Commit**

```bash
git add windows/desktop/release windows/desktop/scripts/Test-Phase2WindowsRelease.ps1 tests/release/test_windows_prebuilt_delivery.py
git commit -m "feat: version and restore managed Windows shortcuts"
```

---

### Task 6: Formal Package and Goal-Integrity Version Contracts

**Files:**
- Modify: `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: `scripts/stamp_windows_goal_integrity.py`
- Modify: `scripts/verify_project_goal_integrity.py`
- Modify: `tests/contract/test_project_goal_integrity.py`
- Modify: `tests/contract/test_windows_goal_integrity_stamper.py`
- Modify: `tests/release/test_windows_goal_integrity_release_contract.py`
- Modify: `tests/release/test_windows_prebuilt_delivery.py`
- Modify: all four native workflows

**Interfaces:**
- Windows build parameters: `ProductVersion` and internal `Version`
- Manifest fields: `product_version`, `version`, existing provenance fields
- Required payload file: `product-version.txt`

- [ ] **Step 1: Write failing package contracts**

```python
assert manifest["product_version"] == "2.3.6.1"
assert "product-version.txt" in {entry["path"] for entry in manifest["files"]}
assert archive.read(f"{root}/payload/product-version.txt").decode().strip() == "2.3.6.1"
assert "2.3.6.1" in package.name
```

Add independent verifier rejection tests for:

- Manifest `product_version = 2.3.6.0`.
- Payload file `2.3.6.0`.
- Non-four-part Manifest value.
- Missing Manifest coverage for `product-version.txt`.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=src python -m pytest \
  tests/contract/test_project_goal_integrity.py \
  tests/contract/test_windows_goal_integrity_stamper.py \
  tests/release/test_windows_goal_integrity_release_contract.py \
  tests/release/test_windows_prebuilt_delivery.py -q
```

Expected: missing product-version contracts cause failure.

- [ ] **Step 3: Separate user version from build ID**

Windows builder signature:

```powershell
param(
    [Parameter(Mandatory)][string]$ProductVersion,
    [Parameter(Mandatory)][string]$Version,
    [string]$OutputRoot = ""
)
```

Validate `ProductVersion` with the exact four-part regex. Formal filename:

```text
PicotooPet-Phase2-Windows-Prebuilt-2.3.6.1-<run>-<short-sha>.zip
```

Manifest example:

```json
{
  "product_version": "2.3.6.1",
  "version": "2.3.6.1-windows-<run>-<short-sha>"
}
```

Mac Core and Worker package filenames also include `2.3.6.1`, run and SHA while preserving their internal role identifiers.

- [ ] **Step 4: Make goal-integrity checks read the unique source**

Add only the source path to the contract:

```json
"product_version_source": "src/picotoopet_core/product-version.txt"
```

Do not duplicate `2.3.6.1` as a second contract value. Stamper and verifier read the source and require:

1. Four-part format.
2. Manifest equals source.
3. Payload file equals source.
4. Payload file hash and size match Manifest.
5. Package filename contains source version.
6. Packaged INSTALL/VERIFY gates compare Manifest with installed `product-version.txt`.

- [ ] **Step 5: Make every workflow read the source once**

Windows step:

```powershell
$productVersion = (Get-Content -LiteralPath src/picotoopet_core/product-version.txt -Raw).Trim()
"PICOTOO_PRODUCT_VERSION=$productVersion" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
```

macOS step:

```bash
echo "PICOTOO_PRODUCT_VERSION=$(tr -d '\r\n' < src/picotoopet_core/product-version.txt)" >> "$GITHUB_ENV"
```

Builders consume `PICOTOO_PRODUCT_VERSION`; workflow YAML does not hardcode `2.3.6.1` elsewhere.

- [ ] **Step 6: Run full contracts and platform syntax checks**

```bash
PYTHONPATH=src python -m pytest tests/contract tests/security tests/release -q
bash -n deploy/macos/phase23/*.command deploy/macos/phase23/lib.sh scripts/mac/phase23/*.sh
bash -n deploy/macos/phase23-worker/*.command deploy/macos/phase23-worker/worker-lib.sh scripts/mac/phase23-worker/*.sh
```

Native Windows:

```powershell
dotnet build windows/desktop/PicotooPet.Desktop.sln --configuration Release --nologo -warnaserror
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected: all contracts pass; one product version value and complete provenance remain.

- [ ] **Step 7: Commit**

```bash
git add windows/desktop/scripts/Build-Phase2WindowsRelease.ps1 contracts/release scripts tests .github/workflows
git commit -m "build: version formal packages as 2.3.6.1"
```

---

### Task 7: Exact-Head Native Verification and Replacement Artifacts

**Files:**
- Update: PR #8 body only after exact-head evidence exists
- Generate: Windows WPF, Mac Core arm64, Mac Worker arm64 packages and evidence

**Interfaces:**
- Input: one frozen 40-character PR head SHA
- Output: three packages, three package SHA-256 values, outer Artifact digests and lifecycle evidence

- [ ] **Step 1: Freeze the candidate**

```bash
git status --short
git rev-parse HEAD
```

Expected: clean tree. Any later code commit invalidates all run evidence and requires a full rerun.

- [ ] **Step 2: Run all four native workflows for that head**

Required success:

```text
.github/workflows/windows-phase2-release.yml
.github/workflows/windows-control-center-ci.yml
.github/workflows/macos-core-slice-b-ci.yml
.github/workflows/macos-worker-slice-c-ci.yml
```

Windows evidence must include contracts, legacy binding RED, STA WPF layout, warnings-as-errors, package stamping, independent verification, PowerShell 5.1 INSTALL/VERIFY/ROLLBACK and Artifact upload.

Mac evidence must include full Python regression, lint, native arm64 confirmation, offline package, Manifest/SHA, INSTALL, VERIFY, ROLLBACK and diagnostic fixtures.

- [ ] **Step 3: Independently verify downloaded artifacts**

```bash
sha256sum <outer-artifact>.zip
unzip -t <outer-artifact>.zip
sha256sum <formal-package>
```

Requirements:

- Outer digest equals GitHub Artifact digest.
- Inner digest equals `.sha256.txt`.
- Windows independent verifier passes.
- Mac Manifest path/size/SHA checks pass.
- Every Manifest reports `product_version: 2.3.6.1`.
- Every evidence file records the frozen source head.

- [ ] **Step 4: Verify package-level user surfaces**

Windows evidence:

```text
window_title = Picotoo Pet AI 2.3.6.1
control_center_subtitle = Control Center · v2.3.6.1
managed shortcut name = Picotoo Pet AI 2.3.6.1.lnk
managed shortcut count = 1 per managed directory
```

Mac Core evidence: live `/api/v1/health.version == 2.3.6.1`.

Mac Worker evidence: active venv `picotoopet_core.__version__ == 2.3.6.1` and the two frozen task types remain registered.

- [ ] **Step 5: Update the Draft PR without merging**

Record exact head, four run IDs, three filenames, three SHA-256 values, shortcut lifecycle evidence and exact live Mac versions. Confirm `draft=true`, `merged=false`, and base/main remain unchanged.

- [ ] **Step 6: Deliver in the fixed order**

1. Mac Core `2.3.6.1` INSTALL → VERIFY.
2. Mac Worker `2.3.6.1` INSTALL → VERIFY.
3. Windows WPF `2.3.6.1` INSTALL.
4. User verifies title, left subtitle, three shortcuts and Task Center diagnostic creation/result.
5. Mark prior `2.3.0-slice-d-*` packages as superseded.

---

## Self-Review

### Spec Coverage

- Version increment rules and single source: Task 1.
- Mac Core live health and VERIFY: Task 2.
- Mac Worker active runtime and VERIFY: Task 3.
- WPF title, left subtitle, STA binding/layout and self-test: Task 4.
- Shortcut replacement, exact state, redirected desktop, failure recovery and rollback: Task 5.
- Package filenames, Manifest, reports, target contract and workflows: Task 6.
- Exact-head native CI, artifact digest and delivery: Task 7.

### Placeholder Scan

No `TBD`, `TODO`, “similar to”, undefined later work or open implementation choice remains.

### Symbol and Field Consistency

- Existing smoke capability constant: `ControlCenterCapabilities.Legacy22`.
- Existing smoke assertion helper: `SmokeAssert.True`.
- Python value: `PRODUCT_VERSION`.
- User-facing JSON field: `product_version`.
- Internal build field: `version`.
- C# provider: `ProductVersionInfo`.
- WPF properties: `WindowTitle`, `ControlCenterSubtitle`.
- PowerShell parameter: `ProductVersion`.
- Pointer snapshot field: `shortcut_state`.
