# Maotai Companion Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有茅台轻量互动宠物组件优化成更像正式产品的一部分，同时保持现有业务边界和稳定性。

**Architecture:** 继续使用现有原生 WPF `PetMascotControl`，只调整 `OperatorHomePage.xaml` 和 `PetMascotControl.xaml/.cs` 的表现参数。测试先扩展现有 `PetMascotWpfSmokeTests`，锁定右侧栏宽度、茅台视觉尺寸、气泡结构和主程序可实例化要求；随后做最小视觉调整并重新跑完整 Windows 与正式安装包验证。

**Tech Stack:** .NET 10、WPF、XAML、现有 GitHub Actions Windows CI/Release workflows。

## Global Constraints

- 只调整 WPF 表现层，不修改 Core、Worker、任务执行、队列、Provider、持久化或发布逻辑。
- 不新增网页、WebView、Rive、Spine 或其他重型运行依赖。
- 继续使用现有高质量 PNG 位图素材。
- 右侧辅助区目标宽度为 300–320px。
- 茅台主体视觉尺寸目标为 260–280px。
- 茅台视觉失败必须局部降级，不能扩散到主程序。
- 不增加新的 AI 后台调用或高频动画。

---

### Task 1: 锁定陪伴型视觉合同

**Files:**
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PetMascotWpfSmokeTests.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj`

**Interfaces:**
- Consumes: `OperatorHomePage`, `PetMascotControl`, XAML 命名元素 `MaotaiMascot`、`MascotImage`、`CalloutBorder`。
- Produces: smoke 合同，确认茅台可实例化、真实位图可加载、首页可承载，并满足陪伴型尺寸范围。

- [ ] **Step 1: 写失败的视觉保护断言**

在现有 `RunContract()` 里增加这些断言：

```csharp
SmokeAssert.True(
    instance.MinWidth >= 300 && instance.MinWidth <= 320,
    "茅台陪伴型组件宽度必须保持在 300–320px");

SmokeAssert.True(
    mascotImage?.Width >= 260 && mascotImage?.Width <= 280,
    "茅台主体视觉尺寸必须保持在 260–280px");

var calloutBorder = instance.FindName("CalloutBorder") as System.Windows.Controls.Border;
SmokeAssert.True(calloutBorder is not null, "茅台控件缺少陪伴型气泡容器");
SmokeAssert.True(
    calloutBorder?.MaxWidth >= 286 && calloutBorder?.MaxWidth <= 304,
    "茅台气泡宽度必须与陪伴型右栏比例匹配");
```

- [ ] **Step 2: 运行 smoke，确认当前版本因尺寸合同失败**

Run:

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: `MAOTAI_PET_WPF_SMOKE=FAIL`，失败原因来自新的陪伴型尺寸断言，而不是 Core/Worker/任务逻辑。

- [ ] **Step 3: 提交 RED 合同**

```bash
git add windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PetMascotWpfSmokeTests.cs
git commit -m "test: lock Maotai companion visual contract"
```

---

### Task 2: 优化茅台和右侧辅助区比例

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml`
- Modify: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml`

**Interfaces:**
- Consumes: 现有 `PendingReviewCount`、`InProgressCount`、`CompletedCount` 绑定和 `NewTaskRequested`、`ProgressRequested` 事件。
- Produces: 300–320px 陪伴型右栏、260–280px 茅台主体、与系统状态卡清晰分层的布局。

- [ ] **Step 1: 把右侧栏从 280px 调整为 312px**

在 `OperatorHomePage.xaml` 把第二列宽度改为：

```xml
<ColumnDefinition Width="312" />
```

同时把茅台与系统状态卡的间距从 `14` 调整为 `20`：

```xml
<pet:PetMascotControl x:Name="MaotaiMascot"
                      Margin="0,0,0,20"
                      PendingReviewCount="{Binding PendingReviewCount, Mode=OneWay}"
                      InProgressCount="{Binding InProgressCount, Mode=OneWay}"
                      CompletedCount="{Binding CompletedCount, Mode=OneWay}"
                      NewTaskRequested="Maotai_NewTaskRequested"
                      ProgressRequested="Maotai_ProgressRequested" />
```

- [ ] **Step 2: 调整 PetMascotControl 的成品比例**

把根控件和主体改为：

```xml
MinWidth="312"
MinHeight="322"
```

把气泡改为：

```xml
MaxWidth="296"
Margin="8,0,8,6"
Padding="15,13"
CornerRadius="18"
```

把舞台和主体改为：

```xml
<Grid x:Name="MascotStage"
      Grid.Row="1"
      MinHeight="270"
      ClipToBounds="False">
```

```xml
<Image x:Name="MascotImage"
       Width="272"
       Height="272"
       HorizontalAlignment="Center"
       VerticalAlignment="Bottom"
       Stretch="Uniform"
       SnapsToDevicePixels="True"
       UseLayoutRounding="True"
       RenderTransformOrigin="0.5,0.62">
```

- [ ] **Step 3: 优化气泡层级和按钮比例**

保持现有配色体系，只做轻量参数调整：按钮 `Padding="12,7"`、按钮圆角 `11`、气泡阴影 `BlurRadius="20"`、`ShadowDepth="4"`、`Opacity="0.12"`。不新增图标、矢量素材或第三方控件。

- [ ] **Step 4: 运行 smoke，确认新视觉合同通过**

Run:

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: `MAOTAI_PET_WPF_SMOKE=PASS`，原有 `PHASE2_CORE_SMOKE=PASS` 保持通过。

- [ ] **Step 5: 提交视觉调整**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Pages/OperatorHomePage.xaml windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml
git commit -m "style: polish Maotai companion layout"
```

---

### Task 3: 收敛动作幅度，不改变行为边界

**Files:**
- Modify: `windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml.cs`
- Test: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PetMascotWpfSmokeTests.cs`

**Interfaces:**
- Consumes: 现有 `OnMouseEnter`、`OnMouseMove`、`StartBreathing`、`PlayClickPulse`。
- Produces: 更克制的 hover、跟随、点击和呼吸动作；事件和状态接口完全不变。

- [ ] **Step 1: 调整 hover 和鼠标跟随幅度**

把 hover 从 `1.03 / 1.6°` 收敛到 `1.022 / 1.2°`，鼠标跟随最大位移从 `±5px / ±2.5px` 收敛到 `±4px / ±2px`。

- [ ] **Step 2: 调整点击反馈和待机幅度**

把点击缩放峰值从 `1.055` 收敛到 `1.04`；Idle 呼吸幅度从 `-2.2px` 收敛到 `-1.8px`。Working、Offline 继续保持现有低幅度节奏。

- [ ] **Step 3: 重新运行 smoke**

Run:

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: `MAOTAI_PET_WPF_SMOKE=PASS` 和 `PHASE2_CORE_SMOKE=PASS`。

- [ ] **Step 4: 提交动作收敛**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Controls/PetMascot/PetMascotControl.xaml.cs
git commit -m "style: refine Maotai companion motion"
```

---

### Task 4: 完整 Windows 与安装包回归验证

**Files:**
- No production file changes unless a regression is found.

**Interfaces:**
- Consumes: Task 1–3 的最终分支 head。
- Produces: CI 和正式安装包验证证据，证明视觉优化没有破坏主程序。

- [ ] **Step 1: 确认 Windows WPF CI 全部通过**

Expected workflow: `Windows Control Center Slice D CI`。

Required successful gates:

```text
Run contract and security tests
Reproduce legacy Task Center binding failure
Run ShellNavigationReconnectWpfSmokeTests and approval Results diagnostic WPF smoke
Build WPF solution with warnings as errors
Run published Control Center self-test
Upload compact WPF evidence
```

- [ ] **Step 2: 确认正式 Windows 安装包流程全部通过**

Expected workflow: `Phase 2.3 Slice D Windows Prebuilt Release`。

Required successful gates:

```text
Build analyze publish and self-test Slice D
Stamp approved native WPF delivery invariants
Validate actual installer against project goal contract
Verify packaged install upgrade recovery and rollback lifecycle on Windows PowerShell 5.1
Upload the single formal Windows installer and lifecycle evidence
```

- [ ] **Step 3: 保持 PR 为 Draft，不合入稳定分支**

确认 PR #34 仍然：

```text
state: open
draft: true
base: feature/operator-simple-mode-2.3.26.1
head: feature/maotai-interactive-pet-lite
```

只有用户后续明确同意合并时，才进入合并步骤。
