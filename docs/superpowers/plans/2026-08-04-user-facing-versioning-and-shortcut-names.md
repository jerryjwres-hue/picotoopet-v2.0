# PicotooPet 用户可见版本号与快捷方式命名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立唯一的四段式产品版本源 `2.3.6.1`，让 Mac Core、Mac Worker、Windows WPF、三个安装包及 INSTALL / VERIFY / ROLLBACK 报告保持一致，并让 Windows 三处快捷方式只保留当前版本名称且可精确回滚。

**Architecture:** 以 `src/picotoopet_core/product-version.txt` 作为仓库内唯一版本值；Python 运行时通过包资源读取，Mac 构建脚本复制同一文件，Windows 项目把同一文件复制到构建和发布输出并由 WPF 运行时读取。内部构建 ID、Git SHA、GitHub run provenance 与安装目录版本继续独立保留，用户版本统一写入 `product_version`。Windows 快捷方式采用“受管名称集合 + 完整状态快照”模型，安装前捕获实际状态，激活后只保留当前版本，失败恢复和回滚按快照还原。

**Tech Stack:** Python 3.12、FastAPI、Bash/macOS LaunchAgent、.NET 10、WPF、C#、Windows PowerShell 5.1、PowerShell 7、GitHub Actions、pytest。

## Global Constraints

- 当前用户版本固定为 `2.3.6.1`。
- 同一功能修复只递增第四段；下一项正常功能递增第三段并把第四段重置为 `1`。
- 唯一值源是 `src/picotoopet_core/product-version.txt`；不得在各组件维护独立用户版本常量。
- Windows 左上角必须显示 `Control Center · v2.3.6.1`。
- Windows 窗口标题必须显示 `Picotoo Pet AI 2.3.6.1`。
- 桌面、开始菜单、启动项只保留 `Picotoo Pet AI 2.3.6.1.lnk`。
- 只删除三个受管目录内名称为 `Picotoo Pet AI.lnk` 或匹配 `Picotoo Pet AI <四段版本>.lnk` 的快捷方式；不得扫描或删除其他目录。
- 回滚必须恢复安装前或目标历史版本记录的快捷方式名称、目标、参数、工作目录、图标和描述。
- `version` 可继续表示内部唯一构建 ID；`product_version` 必须始终表示 `2.3.6.1`。
- 不改变 Mac Core + SQLite Queue/Outbox 事实源、Mac Worker 执行边界或 Windows 原生 WPF 产品形态。
- 不在用户 Windows 或 Mac 上编译。
- PR #8 保持 Draft、open、unmerged；不得修改或合并 `main`。

---

## File Map

### 新建

- `src/picotoopet_core/product-version.txt`：唯一产品版本值。
- `src/picotoopet_core/versioning.py`：Python 包资源读取和四段式格式验证。
- `tests/unit/test_product_version.py`：唯一版本源和解析器单元回归。
- `tests/integration/api/test_product_version_api.py`：真实 FastAPI health 版本回归。
- `windows/desktop/src/PicotooPet.Desktop/Versioning/ProductVersionInfo.cs`：Windows 运行时读取与用户文案格式化。
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/ProductVersionWpfSmokeTests.cs`：STA WPF 版本绑定与布局回归。

### 修改

- `pyproject.toml`：把 `product-version.txt` 纳入 Python 包数据。
- `src/picotoopet_core/__init__.py`：`__version__` 改为统一版本源。
- `src/picotoopet_core/api/app.py`：继续从 `__version__` 返回 health.version，并由测试锁定。
- `deploy/macos/phase23/lib.sh`、`INSTALL_MAC_CORE_SLICE_B.command`、`VERIFY_MAC_CORE_SLICE_B.command`：Core 报告和运行版本强校验。
- `scripts/mac/phase23/Build-MacCoreSliceBDelta.sh`、`Test-MacCoreSliceBDelta.sh`、`Test-MacCoreSliceBFixture.sh`：Core 包复制版本源并验证。
- `deploy/macos/phase23-worker/worker-lib.sh`、`INSTALL_MAC_WORKER_SLICE_C.command`、`VERIFY_MAC_WORKER_SLICE_C.command`：Worker 报告和激活运行时版本强校验。
- `scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh`、`Test-MacWorkerSliceC.sh`、`Test-MacWorkerSliceCFixture.sh`：Worker 包复制版本源并验证。
- `tests/contract/test_phase23_mac_delta_source.py`、`test_phase23_worker_delivery.py`、`test_phase23_mac_delta_security.py`：Mac 静态交付合同。
- `windows/desktop/src/PicotooPet.Desktop/PicotooPet.Desktop.csproj`：复制统一版本文件到 build/publish 输出。
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs`：暴露窗口标题和左上角副标题。
- `windows/desktop/src/PicotooPet.Desktop/Views/ShellWindow.xaml`：绑定用户版本文案。
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`：运行版本 WPF smoke。
- `windows/desktop/src/PicotooPet.Desktop/Services/AppSelfTest.cs`：把产品版本和两个用户文案写入自测报告。
- `windows/desktop/release/Phase2Prebuilt.Common.ps1`：受管快捷方式识别、快照、创建、验证、清除和恢复。
- `windows/desktop/release/Install-Phase2Prebuilt.ps1`：安装前快照、当前版本快捷方式、恢复语义和报告。
- `windows/desktop/release/Verify-Phase2Prebuilt.ps1`：产品版本与快捷方式唯一性校验。
- `windows/desktop/release/Rollback-Phase2Prebuilt.ps1`：按目标版本保存的快捷方式状态恢复。
- `windows/desktop/scripts/Test-Phase2WindowsRelease.ps1`：无版本、旧版本、当前版本、失败恢复和回滚夹具。
- `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`：区分 `ProductVersion` 与内部 `Version`，生成新包名和 Manifest。
- `contracts/release/project-goal-invariants.json`、`scripts/stamp_windows_goal_integrity.py`、`scripts/verify_project_goal_integrity.py`：产品版本与包内版本文件独立验证。
- `tests/contract/test_phase23_windows_source.py`、`test_project_goal_integrity.py`、`test_windows_goal_integrity_stamper.py`、`tests/release/test_windows_prebuilt_delivery.py`：Windows 发布合同。
- 四条原生 workflow：从唯一版本源读取 `2.3.6.1` 并验证正式 Artifact。

---

### Task 1: 建立唯一产品版本源和 Python 运行时版本

**Files:**
- Create: `src/picotoopet_core/product-version.txt`
- Create: `src/picotoopet_core/versioning.py`
- Create: `tests/unit/test_product_version.py`
- Modify: `src/picotoopet_core/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `picotoopet_core.versioning.PRODUCT_VERSION: str`
- Produces: `picotoopet_core.versioning.parse_product_version(raw: str) -> str`
- Produces: `picotoopet_core.__version__ == PRODUCT_VERSION`
- Consumed by: Mac Core health、Mac Core/Worker 构建、Windows 发布构建和所有版本合同。

- [ ] **Step 1: 写失败单元测试**

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
def test_product_version_rejects_non_four_part_values(value: str) -> None:
    with pytest.raises(ValueError, match="四段"):
        parse_product_version(value)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
PYTHONPATH=src python -m pytest tests/unit/test_product_version.py -q
```

Expected: FAIL，原因是 `product-version.txt` 或 `picotoopet_core.versioning` 尚不存在，或旧 `__version__` 仍为 `2.3.0-slice-c`。

- [ ] **Step 3: 实现最小版本资源和解析器**

`src/picotoopet_core/product-version.txt` 必须只有：

```text
2.3.6.1
```

`src/picotoopet_core/versioning.py` 使用包资源读取，并在 import 时失败关闭：

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

`src/picotoopet_core/__init__.py` 改为：

```python
"""Picotoo Pet V2 Mac Core。"""

from .versioning import PRODUCT_VERSION

__version__ = PRODUCT_VERSION
```

在 `pyproject.toml` 现有 setuptools 配置中加入包数据：

```toml
[tool.setuptools.package-data]
picotoopet_core = ["product-version.txt"]
```

- [ ] **Step 4: 验证源码导入和构建后包资源**

Run:

```bash
PYTHONPATH=src python -m pytest tests/unit/test_product_version.py -q
python -m build --wheel
python -c "import zipfile, pathlib; p=next(pathlib.Path('dist').glob('*.whl')); z=zipfile.ZipFile(p); assert any(n.endswith('picotoopet_core/product-version.txt') for n in z.namelist())"
```

Expected: 测试 PASS，wheel 中存在 `picotoopet_core/product-version.txt`。

- [ ] **Step 5: 提交唯一版本源**

```bash
git add src/picotoopet_core/product-version.txt src/picotoopet_core/versioning.py src/picotoopet_core/__init__.py pyproject.toml tests/unit/test_product_version.py
git commit -m "feat: add canonical product version 2.3.6.1"
```

---

### Task 2: 让 Mac Core health、安装和 VERIFY 使用精确产品版本

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
- Consumes: `picotoopet_core.versioning.PRODUCT_VERSION`
- Produces: `/api/v1/health.version == "2.3.6.1"`
- Produces: Core Manifest/report field `product_version: "2.3.6.1"`
- Produces: `VERIFY_MAC_CORE_SLICE_B.command` 非零退出于 expected/actual 不一致。

- [ ] **Step 1: 写 health 和 VERIFY 失败回归**

新 API 测试复用现有 `TestClient(create_app(settings))` 模式：

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

在 `test_phase23_mac_delta_source.py` 增加静态合同：

```python
def test_core_verify_rejects_wrong_running_product_version() -> None:
    verify = (DEPLOY / "VERIFY_MAC_CORE_SLICE_B.command").read_text(encoding="utf-8")
    assert 'health.get("version") != expected_product_version' in verify
    assert "expected=" in verify
    assert "actual=" in verify
```

- [ ] **Step 2: 运行聚焦测试并确认 RED**

```bash
PYTHONPATH=src python -m pytest \
  tests/integration/api/test_product_version_api.py \
  tests/contract/test_phase23_mac_delta_source.py \
  tests/security/test_phase23_mac_delta_security.py -q
```

Expected: health 版本或 VERIFY 静态合同 FAIL。

- [ ] **Step 3: 把产品版本复制进 Core 包并强校验运行服务**

在 `deploy/macos/phase23/lib.sh` 增加：

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

Core VERIFY 把 expected 传入 Python 并检查真实 health：

```python
health = get("/api/v1/health")
actual = health.get("version")
if actual != expected_product_version:
    raise SystemExit(
        f"Mac Core product version mismatch: expected={expected_product_version!r}, actual={actual!r}"
    )
```

`write_report` 保留现有内部 `runtime_version`，新增：

```python
"product_version": sys.argv[6],
```

Builder 从仓库唯一源复制到包根：

```bash
product_version_file="$repo_root/src/picotoopet_core/product-version.txt"
cp "$product_version_file" "$package_root/product-version.txt"
```

Manifest、包名和安装/VERIFY/回滚报告均写 `product_version`；内部版本目录仍可使用 run/SHA 唯一 ID。

- [ ] **Step 4: 验证 Core 静态合同、真实 API 和 macOS 夹具**

```bash
PYTHONPATH=src python -m pytest \
  tests/unit/test_product_version.py \
  tests/integration/api/test_product_version_api.py \
  tests/contract/test_phase23_mac_delta_source.py \
  tests/security/test_phase23_mac_delta_security.py -q
bash -n deploy/macos/phase23/*.command deploy/macos/phase23/lib.sh scripts/mac/phase23/*.sh
```

在原生 arm64 workflow 中执行：

```bash
scripts/mac/phase23/Build-MacCoreSliceBDelta.sh
scripts/mac/phase23/Test-MacCoreSliceBDelta.sh
```

Expected: 报告明确包含 `product_version: 2.3.6.1`；把 fixture health.version 改为 `2.3.6.0` 时 VERIFY 必须非零退出并打印 expected/actual。

- [ ] **Step 5: 提交 Mac Core 版本一致性**

```bash
git add deploy/macos/phase23 scripts/mac/phase23 tests/integration/api/test_product_version_api.py tests/contract/test_phase23_mac_delta_source.py tests/security/test_phase23_mac_delta_security.py
git commit -m "fix: enforce Mac Core product version 2.3.6.1"
```

---

### Task 3: 让 Mac Worker 包、激活运行时和 VERIFY 使用精确产品版本

**Files:**
- Modify: `deploy/macos/phase23-worker/worker-lib.sh`
- Modify: `deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command`
- Modify: `deploy/macos/phase23-worker/VERIFY_MAC_WORKER_SLICE_C.command`
- Modify: `scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh`
- Modify: `scripts/mac/phase23-worker/Test-MacWorkerSliceC.sh`
- Modify: `scripts/mac/phase23-worker/Test-MacWorkerSliceCFixture.sh`
- Modify: `tests/contract/test_phase23_worker_delivery.py`

**Interfaces:**
- Consumes: canonical `product-version.txt`
- Produces: Worker Manifest/report `product_version: "2.3.6.1"`
- Produces: active `$runtime_root/current/.venv` package version check
- Preserves: `runtime_version: "2.3.0-slice-d-worker"` and supported task types。

- [ ] **Step 1: 写 Worker 版本不一致失败测试**

在 `test_phase23_worker_delivery.py` 增加：

```python
def test_worker_verify_checks_active_runtime_product_version() -> None:
    verify = (DEPLOY / "VERIFY_MAC_WORKER_SLICE_C.command").read_text(encoding="utf-8")
    library = (DEPLOY / "worker-lib.sh").read_text(encoding="utf-8")
    assert "verify_worker_product_version" in verify
    assert "from picotoopet_core import __version__" in library
    assert "expected_product_version" in library
    assert '"product_version"' in library
```

并让包结构测试要求顶层 `product-version.txt` 和 Manifest `product_version`。

- [ ] **Step 2: 运行合同测试并确认 RED**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_worker_delivery.py -q
```

Expected: 缺少运行时版本检查和 `product_version` 字段而 FAIL。

- [ ] **Step 3: 实现 Worker 激活版本检查和报告字段**

在 `worker-lib.sh` 增加：

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

Worker VERIFY 的顺序固定为：解析包内 `product-version.txt` → 校验 active venv 的 `__version__` → 等待在线状态 → 校验两个冻结 task type → 写 VERIFY 报告。

`write_worker_report` 增加 `product_version`，但保留：

```python
"runtime_version": "2.3.0-slice-d-worker",
"worker_supported_task_types": [
    "system.diagnostic_snapshot",
    "system.noop",
],
```

Worker builder 复制唯一版本文件、写 Manifest，并把正式包名改为包含 `2.3.6.1` 和 run/SHA。

- [ ] **Step 4: 验证 Worker 夹具和错误版本拒绝**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_worker_delivery.py -q
bash -n deploy/macos/phase23-worker/*.command deploy/macos/phase23-worker/worker-lib.sh scripts/mac/phase23-worker/*.sh
```

原生 arm64 workflow 执行：

```bash
scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh
scripts/mac/phase23-worker/Test-MacWorkerSliceC.sh
```

Expected: 正常 active venv PASS；夹具把包内版本改成 `2.3.6.0` 时 VERIFY 非零退出；Worker 状态和两个 task type 继续 PASS。

- [ ] **Step 5: 提交 Mac Worker 版本一致性**

```bash
git add deploy/macos/phase23-worker scripts/mac/phase23-worker tests/contract/test_phase23_worker_delivery.py
git commit -m "fix: enforce Mac Worker product version 2.3.6.1"
```

---

### Task 4: 在 Windows WPF 左上角、窗口标题和自测中显示统一版本

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
- Produces: `ShellViewModel.WindowTitle` and `ShellViewModel.ControlCenterSubtitle`

- [ ] **Step 1: 写静态合同和 STA WPF 失败回归**

静态合同要求 XAML 不再硬编码 Slice B：

```python
def test_shell_binds_canonical_product_version_surfaces() -> None:
    shell = read("Views/ShellWindow.xaml")
    view_model = read("ViewModels/ShellViewModel.cs")
    assert 'Title="{Binding WindowTitle, Mode=OneWay}"' in shell
    assert 'Text="{Binding ControlCenterSubtitle, Mode=OneWay}"' in shell
    assert "Control Center · Slice B" not in shell
    assert "ProductVersionInfo.WindowTitle" in view_model
    assert "ProductVersionInfo.ControlCenterSubtitle" in view_model
```

STA smoke 使用真实 `Window`、`TextBlock`、WPF Binding 和布局：

```csharp
internal static class ProductVersionWpfSmokeTests
{
    public static void Run()
    {
        var viewModel = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.SliceB);
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
        Assert(window.Title == "Picotoo Pet AI 2.3.6.1", "窗口标题版本错误");
        Assert(subtitle.Text == "Control Center · v2.3.6.1", "左上角版本错误");
        window.Close();
    }
}
```

- [ ] **Step 2: 运行测试并确认 RED**

```bash
PYTHONPATH=src python -m pytest tests/contract/test_phase23_windows_source.py -q
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: 静态合同 FAIL；C# 文件或属性不存在导致构建 FAIL。

- [ ] **Step 3: 实现 Windows 产品版本提供器和绑定**

在 csproj 中把唯一版本文件链接到输出：

```xml
<Content Include="..\..\..\..\src\picotoopet_core\product-version.txt"
         Link="product-version.txt">
  <CopyToOutputDirectory>PreserveNewest</CopyToOutputDirectory>
  <CopyToPublishDirectory>Always</CopyToPublishDirectory>
</Content>
```

`ProductVersionInfo.cs` 必须失败关闭：

```csharp
public static class ProductVersionInfo
{
    public const string FileName = "product-version.txt";
    private static readonly Regex Pattern = new(
        "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$",
        RegexOptions.CultureInvariant);

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

`ShellViewModel` 暴露只读属性；`ShellWindow.xaml` 用 OneWay 绑定。`AppSelfTest` 写入：

```json
{
  "product_version": "2.3.6.1",
  "window_title": "Picotoo Pet AI 2.3.6.1",
  "control_center_subtitle": "Control Center · v2.3.6.1"
}
```

- [ ] **Step 4: 运行真实 WPF、warnings-as-errors 和发布自测**

```powershell
dotnet run `
  --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj `
  --configuration Release

dotnet build windows/desktop/PicotooPet.Desktop.sln `
  --configuration Release `
  --nologo `
  -warnaserror
```

Expected: `ProductVersionWpfSmokeTests.Run()` PASS；现有 TaskCenter `Measure / Arrange / UpdateLayout` 继续 PASS；自测报告三个字段精确匹配。

- [ ] **Step 5: 提交 Windows 用户版本显示**

```bash
git add windows/desktop/src/PicotooPet.Desktop windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests tests/contract/test_phase23_windows_source.py
git commit -m "feat: show product version 2.3.6.1 in WPF"
```

---

### Task 5: 实现版本化快捷方式替换、完整快照和回滚

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
- Pointer field: `shortcut_state`，记录目标版本激活后的三处完整快捷方式状态。

- [ ] **Step 1: 先扩展合同测试和 Windows 生命周期夹具**

Python 静态测试要求以下标记存在：

```python
def test_versioned_shortcuts_are_snapshotted_and_restored() -> None:
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

PowerShell fixture 增加 `Set-PackageProductVersion`，同时更新 Manifest、`payload/product-version.txt`、SHA-256 和 size：

```powershell
function Set-PackageProductVersion {
    param([string]$PackageRoot, [string]$ProductVersion)
    $manifestPath = Join-Path $PackageRoot "release-manifest.json"
    $manifest = Read-JsonUtf8 -Path $manifestPath
    $versionFile = Join-Path $PackageRoot "payload\product-version.txt"
    [IO.File]::WriteAllText($versionFile, "$ProductVersion`n", [Text.UTF8Encoding]::new($false))
    $entry = $manifest.files | Where-Object { $_.path -eq "product-version.txt" } | Select-Object -First 1
    $entry.sha256 = (Get-FileHash -LiteralPath $versionFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $entry.size_bytes = (Get-Item -LiteralPath $versionFile).Length
    $manifest.product_version = $ProductVersion
    Write-JsonUtf8 -Value $manifest -Path $manifestPath
}
```

Fixture 场景固定为：

1. 三个目录预置 `Picotoo Pet AI.lnk`，包含 target、arguments、working directory、icon、description。
2. 安装旧产品版本 `2.3.5.9`，断言无版本快捷方式消失，只存在 `Picotoo Pet AI 2.3.5.9.lnk`。
3. 安装 `2.3.6.1`，断言旧版本快捷方式消失，只存在当前快捷方式。
4. ROLLBACK，断言恢复 `2.3.5.9` 的名称与全部属性。
5. 激活失败恢复夹具，断言恢复安装前无版本快捷方式的名称与全部属性。
6. 对普通桌面和 OneDrive/重定向桌面各执行一次。

- [ ] **Step 2: 运行合同测试确认 RED**

```bash
PYTHONPATH=src python -m pytest tests/release/test_windows_prebuilt_delivery.py -q
```

原生 Windows：

```powershell
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected: 缺少新函数、旧路径仍固定为 `Picotoo Pet AI.lnk` 或快照属性未恢复而 FAIL。

- [ ] **Step 3: 实现受管快捷方式模型**

`Phase2Prebuilt.Common.ps1` 的受管名称只允许：

```powershell
$PicotooManagedShortcutPattern = '^Picotoo Pet AI(?: [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)?\.lnk$'
```

快照条目结构固定为：

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

`Set-PicotooShortcuts` 必须先删除三个受管目录中的全部受管名称，再创建：

```powershell
$shortcutName = "Picotoo Pet AI $ProductVersion.lnk"
```

`Assert-PicotooShortcuts -RequireNoLegacy` 必须检查：每个目录恰好一个受管快捷方式、名称精确、目标精确、没有旧无版本或旧四段版本快捷方式。

`Restore-PicotooManagedShortcutSnapshot` 必须先清空三个目录内受管名称，再按快照逐项还原全部 COM 属性；目标不存在时失败，不得静默创建坏快捷方式。

- [ ] **Step 4: 接入 INSTALL / VERIFY / ROLLBACK 指针和恢复流程**

INSTALL 在写 current pointer 前：

```powershell
$preActivationShortcutState = Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory
```

如果存在旧 current pointer，把当前实际快照写入其 `shortcut_state` 后再保存为 previous pointer。新 current pointer 在创建并验证当前快捷方式后写入自己的 `shortcut_state`。

安装失败恢复使用 `$preActivationShortcutState`，而不是根据旧 executable 重新生成名称。

ROLLBACK 使用目标 `$previous.shortcut_state` 精确恢复；如果旧指针来自历史包且缺少该字段，允许一次兼容回退：根据 `$previous.product_version` 和 executable 创建版本化快捷方式，并在报告中写 `shortcut_restore_mode: "legacy-pointer-fallback"`。新 `2.3.6.1` 指针必须始终有 snapshot，不得走兼容回退。

VERIFY 检查 Manifest `product_version`、current pointer `product_version`、三个快捷方式名称及目标一致。

- [ ] **Step 5: 运行完整 Windows PowerShell 5.1 生命周期**

```powershell
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected:

- normal desktop PASS；
- redirected OneDrive desktop PASS；
- unversioned → `2.3.5.9` → `2.3.6.1` 替换 PASS；
- rollback 恢复 `2.3.5.9` 全属性 PASS；
- intentional activation failure 恢复无版本快捷方式全属性 PASS；
- 三处目录均无多余受管快捷方式。

- [ ] **Step 6: 提交快捷方式生命周期**

```bash
git add windows/desktop/release windows/desktop/scripts/Test-Phase2WindowsRelease.ps1 tests/release/test_windows_prebuilt_delivery.py
git commit -m "feat: version and restore managed Windows shortcuts"
```

---

### Task 6: 把产品版本纳入 Windows 包、目标合同、四条 workflow 和三平台文件名

**Files:**
- Modify: `windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`
- Modify: `contracts/release/project-goal-invariants.json`
- Modify: `scripts/stamp_windows_goal_integrity.py`
- Modify: `scripts/verify_project_goal_integrity.py`
- Modify: `tests/contract/test_project_goal_integrity.py`
- Modify: `tests/contract/test_windows_goal_integrity_stamper.py`
- Modify: `tests/release/test_windows_goal_integrity_release_contract.py`
- Modify: `tests/release/test_windows_prebuilt_delivery.py`
- Modify: `.github/workflows/windows-phase2-release.yml`
- Modify: `.github/workflows/windows-control-center-ci.yml`
- Modify: `.github/workflows/macos-core-slice-b-ci.yml`
- Modify: `.github/workflows/macos-worker-slice-c-ci.yml`

**Interfaces:**
- Windows builder parameter: `-ProductVersion 2.3.6.1`
- Windows builder parameter: `-Version <internal-build-id>` 保留。
- Manifest fields: `product_version`, `version`, existing provenance fields。
- Required payload path: `product-version.txt`。

- [ ] **Step 1: 写发布合同失败测试**

Windows 包测试要求：

```python
assert manifest["product_version"] == "2.3.6.1"
assert "product-version.txt" in {entry["path"] for entry in manifest["files"]}
assert archive.read(f"{root}/payload/product-version.txt").decode().strip() == "2.3.6.1"
assert "2.3.6.1" in package.name
```

独立校验器测试增加三类拒绝：

```python
with pytest.raises(GoalIntegrityError, match="product version"):
    verify_windows_package(package_with_manifest_version("2.3.6.0"))
with pytest.raises(GoalIntegrityError, match="product-version.txt"):
    verify_windows_package(package_with_payload_version("2.3.6.0"))
with pytest.raises(GoalIntegrityError, match="四段"):
    verify_windows_package(package_with_manifest_version("slice-d"))
```

Workflow 合同要求四条 workflow 都从唯一文件读取，而不是硬编码四份：

```yaml
- name: Read canonical product version
  shell: bash
  run: echo "PICOTOO_PRODUCT_VERSION=$(tr -d '\r\n' < src/picotoopet_core/product-version.txt)" >> "$GITHUB_ENV"
```

Windows 使用 PowerShell 等价写入 `$env:GITHUB_ENV`。

- [ ] **Step 2: 运行发布合同并确认 RED**

```bash
PYTHONPATH=src python -m pytest \
  tests/contract/test_project_goal_integrity.py \
  tests/contract/test_windows_goal_integrity_stamper.py \
  tests/release/test_windows_goal_integrity_release_contract.py \
  tests/release/test_windows_prebuilt_delivery.py -q
```

Expected: Manifest、包名、payload 或 workflows 缺少 `product_version` 而 FAIL。

- [ ] **Step 3: 区分用户版本与内部构建 ID**

Windows builder 签名改为：

```powershell
param(
    [Parameter(Mandatory)][string]$ProductVersion,
    [Parameter(Mandatory)][string]$Version,
    [string]$OutputRoot = ""
)
```

并验证：

```powershell
if ($ProductVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "ProductVersion 必须是四段数字。"
}
```

正式文件名：

```text
PicotooPet-Phase2-Windows-Prebuilt-2.3.6.1-<run>-<short-sha>.zip
```

Manifest 同时写：

```json
{
  "product_version": "2.3.6.1",
  "version": "2.3.6.1-windows-<run>-<short-sha>"
}
```

Mac Core 和 Worker 正式包名同样包含 `2.3.6.1`，后部保留 run/SHA；其 role-specific runtime_version 保留不变。

- [ ] **Step 4: 强化 stamper、独立 verifier 和运行时 INSTALL/VERIFY**

`project-goal-invariants.json` 增加唯一版本文件路径：

```json
"product_version_source": "src/picotoopet_core/product-version.txt"
```

stamper 和 verifier 每次从该路径读取 expected，验证：

1. 格式为四段数字；
2. Manifest `product_version` 等于 expected；
3. payload `product-version.txt` 等于 expected；
4. 文件被 Manifest 精确覆盖，SHA-256 和 size 重算一致；
5. 包名包含 expected；
6. INSTALL 和 VERIFY runtime gate 均比较 Manifest 与已安装 `product-version.txt`。

不要把 `2.3.6.1` 再复制进 contract JSON 的值字段，避免出现第二个版本值源。

- [ ] **Step 5: 运行全部合同和跨平台语法检查**

```bash
PYTHONPATH=src python -m pytest tests/contract tests/security tests/release -q
bash -n deploy/macos/phase23/*.command deploy/macos/phase23/lib.sh scripts/mac/phase23/*.sh
bash -n deploy/macos/phase23-worker/*.command deploy/macos/phase23-worker/worker-lib.sh scripts/mac/phase23-worker/*.sh
```

原生 Windows：

```powershell
dotnet build windows/desktop/PicotooPet.Desktop.sln --configuration Release --nologo -warnaserror
.\windows\desktop\scripts\Invoke-Phase2WindowsReleaseLifecycleGate.ps1
```

Expected: 所有合同 PASS；包内只有一个版本值；内部 build ID 和 provenance 仍完整。

- [ ] **Step 6: 提交发布合同和 workflow**

```bash
git add windows/desktop/scripts/Build-Phase2WindowsRelease.ps1 contracts/release scripts tests .github/workflows
git commit -m "build: version formal packages as 2.3.6.1"
```

---

### Task 7: 对精确最终 SHA 运行四条原生门并发布替换包

**Files:**
- Modify: PR #8 body/status only after exact-head evidence exists。
- Generated artifacts: Windows WPF、Mac Core arm64、Mac Worker arm64 及报告和 SHA-256。

**Interfaces:**
- Input: 精确 PR head SHA。
- Output: 三个正式预编译包、三份内部 SHA-256、GitHub Artifact digest、INSTALL/VERIFY/ROLLBACK evidence。

- [ ] **Step 1: 冻结候选 SHA 并确认没有未提交改动**

```bash
git status --short
git rev-parse HEAD
```

Expected: working tree clean；记录完整 40 字符 SHA。此后任何代码提交都会使现有原生证据失效并要求重跑。

- [ ] **Step 2: 运行四条精确 head 原生 workflow**

必须全部为 success：

```text
.github/workflows/windows-phase2-release.yml
.github/workflows/windows-control-center-ci.yml
.github/workflows/macos-core-slice-b-ci.yml
.github/workflows/macos-worker-slice-c-ci.yml
```

Windows 必须完成：发布合同、legacy binding RED、真实 WPF layout、warnings-as-errors、包盖章、独立 verifier、PowerShell 5.1 INSTALL/VERIFY/ROLLBACK、Artifact 上传。

Mac Core/Worker 必须完成：完整 Python 回归、lint、arm64 环境确认、离线包、Manifest/SHA、安装、VERIFY、回滚和诊断闭环夹具。

- [ ] **Step 3: 下载 Artifact 并独立重算摘要**

对每个外层 Artifact ZIP：

```bash
sha256sum <artifact>.zip
unzip -t <artifact>.zip
```

对三个正式内层包：

```bash
sha256sum <formal-package>
```

要求：

- 外层摘要等于 GitHub Artifact digest；
- 内层摘要等于上传的 `.sha256.txt`；
- Windows ZIP 独立 verifier PASS；
- Mac tar.gz Manifest 每个路径、size、SHA PASS；
- 三个 Manifest 的 `product_version` 均为 `2.3.6.1`；
- 所有 evidence 的 source head 等于冻结 SHA。

- [ ] **Step 4: 做安装包级版本验收**

Windows evidence 必须证明：

```text
窗口标题: Picotoo Pet AI 2.3.6.1
左上角: Control Center · v2.3.6.1
快捷方式: Picotoo Pet AI 2.3.6.1.lnk × 3
旧受管快捷方式: 0
```

Mac Core VERIFY 必须报告运行 health.version `2.3.6.1`；Mac Worker VERIFY 必须报告 active venv `__version__ == 2.3.6.1`，并继续报告两个支持任务类型。

- [ ] **Step 5: 更新 Draft PR 证据，不合并 main**

PR body 写入：

- exact source SHA；
- 四条 run ID/run number/conclusion；
- 三个包文件名与 SHA-256；
- `product_version: 2.3.6.1`；
- Windows 三处快捷方式版本化和回滚证据；
- Mac Core/Worker exact running version 证据；
- PR 仍 Draft、open、unmerged。

- [ ] **Step 6: 交付替换安装顺序**

正式交付顺序：

1. Mac Core `2.3.6.1` INSTALL → VERIFY；
2. Mac Worker `2.3.6.1` INSTALL → VERIFY；
3. Windows WPF `2.3.6.1` INSTALL；
4. 用户确认左上角、窗口标题、三处快捷方式和 Task Center 诊断任务；
5. 旧 `2.3.0-slice-d-*` 包标记为被 `2.3.6.1` 取代，不再推荐安装。

---

## Plan Self-Review

### Spec coverage

- 四段式规则与当前版本：Task 1。
- Mac Core health 和 VERIFY：Task 2。
- Mac Worker active runtime、报告和 VERIFY：Task 3。
- Windows 左上角、窗口标题、真实 STA WPF 和自测：Task 4。
- 三处快捷方式替换、OneDrive、失败恢复和精确回滚：Task 5。
- 三平台 Manifest、包名、报告、目标合同和 workflows：Task 6。
- 四条原生门、Artifact 摘要、正式交付和 Draft PR：Task 7。

### Placeholder scan

计划不含 `TBD`、`TODO`、未定义的“适当处理”或“类似 Task N”。每个新增接口、字段、文件和测试命令均有明确名称。

### Type and field consistency

- Python 唯一值：`PRODUCT_VERSION: str`。
- Manifest/报告用户字段：`product_version`。
- 内部唯一构建字段：`version`。
- Windows C#：`ProductVersionInfo.Current`、`WindowTitle`、`ControlCenterSubtitle`。
- Windows pointer：`shortcut_state`。
- PowerShell 参数：`ProductVersion`。
- 所有任务均使用同一精确值 `2.3.6.1`。
