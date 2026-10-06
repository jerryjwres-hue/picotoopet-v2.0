# 茅台桌宠 v2：自然动作系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前“完整 PNG 裁切 + 低频 DispatcherTimer”桌宠替换成连续时间驱动的 Q 版阿拉斯加「茅台」自然动作系统，稳定实现走、跑、跳、落地、坐、趴、工作敲键盘、疲劳/烦躁与用户互动，并消除可见撕裂、硬切和明显卡帧。

**Architecture:** 保留现有 `PetPresentation` 作为唯一业务状态真相源，新增纯表现层 `Motion Engine -> Animation Graph -> Locomotion/IK/Spring -> PoseFrame -> Raster Renderer`。渲染使用 WPF `CompositionTarget.Rendering` 与固定逻辑坐标，每帧只更新已缓存 Image/Transform，不在帧循环中加载图片、扫描目录、访问 Core/Worker 或分配高频临时对象。

**Tech Stack:** C# / .NET 10 / WPF / `CompositionTarget.Rendering` / `Canvas` / `Image` / `TransformGroup` / deterministic smoke tests / GitHub Actions Windows runner。

## Global Constraints

- `PetPresentation` 继续是 Base State 唯一来源；Core、Worker、Task、Approval、Queue/Outbox、Result、Schema 不允许被桌宠写入。
- 不使用 WebView/Electron、远程素材、Provider 调用或远程 AI 推理。
- 不再使用“同一完整 Source + Clip 裁头/爪/尾”作为可见主路径。
- 所有 v2 美术部件均为独立透明 PNG，关节保留隐藏重叠毛发区，固定白名单加载。
- 每帧动画推进使用 `deltaTime`；`deltaTime` clamp 到 `0..0.05s`，避免窗口卡顿后一次跨越巨大距离。
- Render Loop 只在 `Loaded && IsVisible` 期间订阅；隐藏/卸载必须退订。
- 目标逻辑更新为显示刷新节拍；60Hz 环境目标约 60 pose updates/s，不通过 200ms+ Timer 模拟运动。
- 125% / 150% DPI 与窗口缩放必须使用统一逻辑坐标、`UseLayoutRounding`、`SnapsToDevicePixels`。
- 资产失败必须 fail closed：桌宠视觉可降级，Shell 不崩溃。
- 所有新增代码注释保持对齐且只解释约束/原因，不堆砌无意义注释。
- PR 在真实 Windows 视觉验收前保持 Draft；任何自动化全绿都不能替代实机动作观感验收。

---

## File Structure

**Create**

- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiPoseFrame.cs` — 单帧纯数据 Pose，不依赖 WPF 控件。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiSpring.cs` — 临界/欠阻尼次级运动。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiIkSolver.cs` — 两段腿/爪解析 IK。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiAnimationGraph.cs` — 合法状态、Transition、Blend 时间。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiLocomotionController.cs` — 位置、速度、转向、步态相位、跳跃。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiBehaviorPlanner.cs` — 自主行为与业务目标映射，不操作 UI。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiMotionEngine.cs` — 每帧协调并输出 `MaotaiPoseFrame`。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiRasterRenderer.cs` — 仅把 Pose 应用到 WPF 图层。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion/MaotaiAssetManifest.cs` — v2 白名单、Pivot、z-order、逻辑尺寸。
- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/MaotaiNaturalMotionV2SmokeTests.cs` — v2 确定性合同。

**Modify**

- `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs` — 注册 v2 Smoke。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.xaml` — 替换可见裁切 Rig 为真正独立图层。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/AssistantPetPanel.Maotai.cs` — 删除低频动作 Tick 主路径，接入 Render Loop/Engine/Renderer。
- `windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiPetAssetLoader.cs` — v2 独立部件加载、校验与安全 fallback。
- `windows/desktop/src/PicotooPet.Desktop/Views/FloatingPetWindow.xaml(.cs)` — 使用同一 Motion Engine，不复制第二套动作状态机。

---

### Task 1: 先冻结“不能再撕裂”的 RED Contract

**Files:**
- Create: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/MaotaiNaturalMotionV2SmokeTests.cs`
- Modify: `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/Program.cs`

**Interfaces:**
- Produces: `MaotaiNaturalMotionV2SmokeTests.Run()`。
- Consumes: 当前 `AssistantPetPanel.xaml`、`AssistantPetPanel.Maotai.cs` 源文件文本和后续 Motion 类型。

- [ ] **Step 1: 写失败合同，禁止可见同图裁切和低频 Timer 主驱动**

```csharp
internal static class MaotaiNaturalMotionV2SmokeTests
{
    public static void Run()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(Path.Combine(
            root,
            "windows", "desktop", "src", "PicotooPet.Desktop",
            "Views", "Controls", "AssistantPetPanel.xaml"));
        var code = File.ReadAllText(Path.Combine(
            root,
            "windows", "desktop", "src", "PicotooPet.Desktop",
            "Views", "Controls", "AssistantPetPanel.Maotai.cs"));

        Assert(!xaml.Contains("MaotaiHead.Clip", StringComparison.Ordinal),
            "v2 可见角色禁止从完整图裁切 Head");
        Assert(!xaml.Contains("MaotaiLeftPawImage.Clip", StringComparison.Ordinal),
            "v2 可见角色禁止从完整图裁切 Paw");
        Assert(code.Contains("CompositionTarget.Rendering", StringComparison.Ordinal),
            "v2 必须使用连续 Render Loop");
        Assert(!code.Contains("Interval = TimeSpan.FromMilliseconds(220)", StringComparison.Ordinal),
            "v2 禁止 220ms Tick 作为运动主时钟");
    }
}
```

- [ ] **Step 2: 在 `Program.Main` 的 WPF Smoke 区注册 `MaotaiNaturalMotionV2SmokeTests.Run();`**

- [ ] **Step 3: 运行 RED**

Run:

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
```

Expected: FAIL，错误必须来自 v2 裁切/Render Loop 合同，而不是无关编译错误。

- [ ] **Step 4: Commit**

```bash
git add windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "test: freeze Maotai natural motion v2 contracts"
```

---

### Task 2: 建立确定性 Pose、Spring 与 IK 数学核心

**Files:**
- Create: `MaotaiMotion/MaotaiPoseFrame.cs`
- Create: `MaotaiMotion/MaotaiSpring.cs`
- Create: `MaotaiMotion/MaotaiIkSolver.cs`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Produces:
  - `readonly record struct MaotaiBonePose(double X, double Y, double RotationDeg, double ScaleX, double ScaleY)`
  - `sealed class MaotaiPoseFrame` with named bone poses and face state。
  - `MaotaiSpring.Step(double target, double deltaTime)`。
  - `MaotaiIkSolver.SolveTwoBone(...) -> MaotaiTwoBoneSolution`。

- [ ] **Step 1: 写 Spring RED**

```csharp
var spring = new MaotaiSpring(value: 0, velocity: 0, frequencyHz: 5.5, dampingRatio: 0.82);
for (var i = 0; i < 120; i++)
{
    spring.Step(target: 10, deltaTime: 1.0 / 60.0);
}
Assert(Math.Abs(spring.Value - 10) < 0.05, "Spring 2 秒内必须收敛");
Assert(double.IsFinite(spring.Value), "Spring 不允许数值爆炸");
```

- [ ] **Step 2: 写 IK RED**

```csharp
var ik = MaotaiIkSolver.SolveTwoBone(
    rootX: 0, rootY: 0,
    upperLength: 30, lowerLength: 26,
    targetX: 38, targetY: 20,
    bendSign: 1);
Assert(ik.EndError < 0.01, "可达 IK 末端误差过大");
```

- [ ] **Step 3: 实现最小数学核心**

`MaotaiSpring` 使用稳定的二阶阻尼推进；在入口执行：

```csharp
var dt = Math.Clamp(deltaTime, 0.0, 0.05);
```

`MaotaiIkSolver` 使用余弦定理并先将目标距离 clamp 到 `[abs(L1-L2)+epsilon, L1+L2-epsilon]`，保证不可达点不产生 NaN。

- [ ] **Step 4: 运行 Smoke，确认数学测试 PASS 且原 RED 仍因未替换渲染路径失败**

- [ ] **Step 5: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: add deterministic Maotai motion math"
```

---

### Task 3: Animation Graph + Locomotion，先把走跑跳做成连续状态

**Files:**
- Create: `MaotaiMotion/MaotaiAnimationGraph.cs`
- Create: `MaotaiMotion/MaotaiLocomotionController.cs`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Produces:
  - `enum MaotaiMotionState { Idle, Look, Walk, Run, JumpPrep, JumpAir, Land, Sit, LieDown, Sleep, Wake, GetUp, WorkApproach, WorkSettle, WorkTyping, WorkTired, WorkAnnoyed, Yawn, Recover, UserReaction }`
  - `MaotaiAnimationGraph.Request(MaotaiMotionState target)`。
  - `MaotaiAnimationGraph.Update(double dt)`。
  - `MaotaiLocomotionController.Update(double dt, double targetX, bool wantsRun, bool wantsJump)`。

- [ ] **Step 1: 写非法瞬切 RED**

```csharp
var graph = new MaotaiAnimationGraph(MaotaiMotionState.Run);
graph.Request(MaotaiMotionState.Sleep);
Assert(graph.TargetState != MaotaiMotionState.Sleep,
    "Run 不允许瞬间硬切 Sleep；必须经减速/坐/趴路径");
```

- [ ] **Step 2: 写 Jump 顺序 RED**

```csharp
var graph = new MaotaiAnimationGraph(MaotaiMotionState.Idle);
graph.Request(MaotaiMotionState.JumpAir);
Assert(graph.ActiveState == MaotaiMotionState.JumpPrep,
    "Jump 必须先蓄力");
```

- [ ] **Step 3: 实现合法 Transition 表**

最低合法路径必须包含：

```text
Idle -> Walk -> Run
Run -> Walk -> Idle
Idle/Walk -> JumpPrep -> JumpAir -> Land -> Idle
Idle -> Sit -> LieDown -> Sleep -> Wake -> GetUp -> Idle
Idle/Walk -> WorkApproach -> WorkSettle -> WorkTyping
WorkTyping -> WorkTired -> Yawn -> WorkTyping
WorkTyping -> WorkAnnoyed -> Recover -> WorkTyping
AnyInterruptible -> UserReaction -> ResumeLatestBaseState
```

- [ ] **Step 4: Locomotion 使用速度/加速度而不是直接设置坐标**

约束：

```csharp
CurrentSpeed = MoveTowards(CurrentSpeed, desiredSpeed, acceleration * dt);
PositionX   += CurrentSpeed * dt;
GaitPhase    = Wrap01(GaitPhase + Math.Abs(CurrentSpeed) * gaitCyclesPerUnit * dt);
```

Jump 使用连续抛物线或半隐式速度积分；Land 必须有独立状态，不把 `JumpAir` 直接切 `Idle`。

- [ ] **Step 5: 以固定 1/60s 更新 600 帧，断言所有 Position/Velocity/Phase 为 finite 且边界内**

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: add continuous Maotai locomotion graph"
```

---

### Task 4: Motion Engine 输出自然 Pose，包含步态锁脚、重心和次级运动

**Files:**
- Create: `MaotaiMotion/MaotaiBehaviorPlanner.cs`
- Create: `MaotaiMotion/MaotaiMotionEngine.cs`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Produces:
  - `MaotaiMotionEngine.Update(double deltaTime, MaotaiMotionInput input) -> MaotaiPoseFrame`
  - `MaotaiMotionInput` 只含表现所需输入：base mode、pointer、interaction、stage bounds、work anchor。

- [ ] **Step 1: 写 deterministic RED：相同输入序列必须得到相同 Pose**

```csharp
var first  = Simulate(seed: 17, frames: 360);
var second = Simulate(seed: 17, frames: 360);
Assert(first.SequenceEqual(second), "Motion Engine 必须可确定性回归测试");
```

- [ ] **Step 2: 写脚掌支撑相锁地断言**

在 Walk 支撑相连续 8 帧内，对世界坐标脚掌末端：

```csharp
Assert(MaxWorldFootDrift(samples) < 0.75,
    "Walk 支撑相脚掌漂移过大，会产生滑步感");
```

- [ ] **Step 3: 实现 Walk/Run Pose**

- 四腿错相，不使用四肢同步摆动。
- Body Y 使用小幅正弦重心起伏。
- Head 通过 Spring 跟随 Body，不刚性绑定。
- TailBase/Mid/Tip 使用递增相位延迟和阻尼。
- 耳朵使用较小幅度延迟跟随。
- 支撑相调用 IK 把 Paw 锁在保存的世界落点。

- [ ] **Step 4: 实现 JumpPrep/Air/Land Pose**

- Prep: torso 下压、腿压缩、尾巴稍抬。
- Air: torso 连续弧线、腿收拢。
- Land: torso squash，随后 spring 恢复；耳/尾有 1~3 帧视觉延迟的阻尼响应。

- [ ] **Step 5: 实现 Pointer 层级跟随**

顺序固定为：`pupil target -> head spring -> ear spring`。对 Head Rotation 设置最大角速度和角加速度，禁止鼠标瞬移时锁头。

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls/MaotaiMotion windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: generate natural Maotai pose frames"
```

---

### Task 5: 真正独立 Raster Skeleton，彻底移除可见裁图路径

**Files:**
- Create: `MaotaiMotion/MaotaiAssetManifest.cs`
- Create: `MaotaiMotion/MaotaiRasterRenderer.cs`
- Modify: `MaotaiPetAssetLoader.cs`
- Modify: `AssistantPetPanel.xaml`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Produces: `MaotaiAssetManifest.V2`、`MaotaiRasterRenderer.Apply(MaotaiPoseFrame frame)`。

- [ ] **Step 1: 写资产白名单 RED**

至少固定以下独立资产名：

```text
torso_neutral.png
head.png
ear_left.png
ear_right.png
eye_left_open.png
eye_right_open.png
pupil_left.png
pupil_right.png
mouth_smile.png
mouth_tired.png
mouth_annoyed.png
front_left_upper.png
front_left_lower.png
front_left_paw.png
front_right_upper.png
front_right_lower.png
front_right_paw.png
hind_left_upper.png
hind_left_lower.png
hind_left_paw.png
hind_right_upper.png
hind_right_lower.png
hind_right_paw.png
tail_base.png
tail_mid.png
tail_tip.png
headphone_band.png
headphone_left.png
headphone_right.png
laptop.png
drink.png
shadow.png
```

`IsKnownAsset` 必须拒绝路径分隔符、`..` 与未列入 manifest 的文件。

- [ ] **Step 2: XAML 改为每个部件一个独立 `Image`，每层有固定 Pivot/Z-order**

禁止出现以下结构：

```xml
<Image Source="{sameFullCharacterSource}">
  <Image.Clip>...</Image.Clip>
</Image>
```

保留旧 vector 层仅作为不可见兼容契约，且 `IsHitTestVisible="False"`。

- [ ] **Step 3: 资产加载只在初始化时进行**

`MaotaiPetAssetLoader`：

- 目录固定为 `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v2`。
- 单次加载 `BitmapCacheOption.OnLoad` + `Freeze()`。
- 失败返回冻结透明 `DrawingImage` 或明确的单部件 fallback；异常不穿透。
- 每帧禁止重新访问文件系统。

- [ ] **Step 4: Renderer 只更新 Transform/Opacity**

`Apply` 内禁止文件 IO、字符串拼接、LINQ、集合创建；使用构造时缓存的 `Image`/`RotateTransform`/`TranslateTransform` 引用。

- [ ] **Step 5: 跑 Task 1 RED，确认“裁切合同”转 GREEN**

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: replace clipped Maotai art with independent raster skeleton"
```

---

### Task 6: 用 `CompositionTarget.Rendering` 接入 60Hz 连续帧，消灭卡顿主因

**Files:**
- Modify: `AssistantPetPanel.Maotai.cs`
- Modify: `AssistantPetPanel.xaml`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Consumes: `MaotaiMotionEngine.Update`、`MaotaiRasterRenderer.Apply`。

- [ ] **Step 1: 写 lifecycle RED**

合同必须能从源码或可测状态确认：Loaded/Visible 订阅一次，Hidden/Unloaded 退订一次，不重复订阅。

- [ ] **Step 2: 删除 `_maotaiTimer` 作为运动主时钟**

保留低频业务轮询只能用于不影响姿态的辅助事件；所有骨骼运动必须来自 Rendering：

```csharp
private void OnMaotaiRendering(object? sender, EventArgs e)
{
    var now = _maotaiClock.Elapsed.TotalSeconds;
    var dt  = Math.Clamp(now - _maotaiLastSeconds, 0.0, 0.05);
    _maotaiLastSeconds = now;

    var input = BuildMotionInput();
    var frame = _maotaiMotionEngine.Update(dt, input);
    _maotaiRenderer.Apply(frame);
}
```

- [ ] **Step 3: Render loop 不做业务查询**

`BuildMotionInput()` 只能读取已缓存的 `_activeMode`、pointer state、interaction state、stage dimensions；不能调用网络、Provider、Core API 或磁盘。

- [ ] **Step 4: 加入长帧保护**

模拟 250ms stall 后只允许使用 50ms dt；位置变化不允许一次越过舞台边界。

- [ ] **Step 5: 加 `UseLayoutRounding="True"` / `SnapsToDevicePixels="True"` 并确认 125% / 150% 逻辑坐标不依赖物理像素常量**

- [ ] **Step 6: 运行完整 WPF Smoke 与 warnings-as-errors build**

```powershell
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
dotnet build windows/desktop/PicotooPet.Desktop.sln -c Release /warnaserror
```

Expected: 两条命令均 exit 0。

- [ ] **Step 7: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: drive Maotai motion from WPF render loop"
```

---

### Task 7: 工作、疲劳、烦躁与用户互动全部通过动画图自然插入

**Files:**
- Modify: `MaotaiMotion/MaotaiBehaviorPlanner.cs`
- Modify: `MaotaiMotion/MaotaiMotionEngine.cs`
- Modify: `AssistantPetPanel.Maotai.cs`
- Modify: `FloatingPetWindow.xaml.cs`
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`

**Interfaces:**
- Base state priority: Error/Offline > user interaction > task-driven state > autonomous behavior。

- [ ] **Step 1: 写 Working 路径 RED**

```text
Idle/Walk -> WorkApproach -> WorkSettle -> WorkTyping
```

断言 `WorkTyping` 之前角色 X 已进入 laptop anchor 容差范围，禁止“原地瞬间出现电脑前”。

- [ ] **Step 2: Typing 使用前爪 IK 对准左右键盘锚点**

左右爪相位错开；头部大部分时间看屏幕；眨眼/视线扫动不改变前爪目标。

- [ ] **Step 3: Tired/Annoyed 不换整张角色图**

疲劳由眼皮、眉毛、嘴型、耳朵姿态、打字 cadence、torso tension 共同形成；烦躁同理。禁止 `ApplyMaotaiSource(_maotaiWorkingTired...)` 作为 v2 主表现。

- [ ] **Step 4: 用户互动 RED**

用户 MouseMove/Pat/Paw/DoubleClick/Drag 到来时：

```csharp
Assert(planner.Priority == MaotaiBehaviorPriority.UserInteraction,
    "用户互动必须高于自主行为");
```

交互结束后 `ResumeLatestBaseState` 必须读取当前 `_activeMode`，不能恢复旧快照。

- [ ] **Step 5: Floating Pet 复用同一个 Engine 模型**

悬浮窗口只改变 stage bounds / locomotion range / edge-snap policy；不得复制第二份行为状态机。

- [ ] **Step 6: Commit**

```bash
git add windows/desktop/src/PicotooPet.Desktop/Views/Controls windows/desktop/src/PicotooPet.Desktop/Views/FloatingPetWindow.xaml.cs windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests
git commit -m "feat: add natural Maotai work and interaction transitions"
```

---

### Task 8: 卡帧/异常/兼容性 Soak Gate 与正式 Windows 验证

**Files:**
- Modify: `MaotaiNaturalMotionV2SmokeTests.cs`
- Modify: PR description after all gates pass。

**Interfaces:**
- Produces: 可审计的 v2 验证证据，不用主观“看起来应该没问题”替代测试。

- [ ] **Step 1: 10 分钟等价 deterministic soak**

不等待真实 10 分钟；用 36,000 次 `1/60s` Update 模拟 600 秒，混入每 600 帧一次 80~250ms stall（进入 engine 前 clamp），断言：

```csharp
Assert(AllFinite(frames), "Soak 中出现 NaN/Infinity");
Assert(MaxStageOverflow(frames) <= 0.01, "角色越过舞台约束");
Assert(MaxSingleFrameTranslation(frames) < configuredTeleportThreshold,
    "检测到单帧瞬移/卡顿补帧");
```

- [ ] **Step 2: 资产损坏 Gate**

对缺失/截断 PNG 调用 loader，必须返回安全 fallback；构造 `AssistantPetPanel`/Shell 不抛 `FileFormatException`。

- [ ] **Step 3: 业务写入禁止 Gate**

扫描 v2 公开类型，禁止出现 `Approve`, `Reject`, `CreateTask`, `CancelTask`, `Save`, `Connect` 等业务写入方法。

- [ ] **Step 4: 完整本地/CI 命令**

```powershell
python -m pytest -q tests/contract tests/security
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj --configuration Release
dotnet build windows/desktop/PicotooPet.Desktop.sln -c Release /warnaserror
```

Expected: contract/security 无失败；Smoke exit 0；build 0 warnings / 0 errors。

- [ ] **Step 5: GitHub Windows Control Center Slice D CI 必须全绿**

确认：contract/security、legacy Task Center regression、WPF smoke、warnings-as-errors build、published self-test、evidence upload 全部 success。

- [ ] **Step 6: Phase 2.3 Slice D Windows Prebuilt Release 必须全绿**

确认：release analyzer、build/publish/self-test、delivery invariants、installer validation、install/upgrade/recovery/rollback、artifact upload 全部 success。

- [ ] **Step 7: 真实 Windows 视觉验收**

必须人工观察并通过：

- 走路无明显脚滑、部件接缝、重影。
- Walk/Run 切换没有 Pose 瞬跳。
- Jump 有蓄力、空中、落地压缩和回弹。
- 鼠标快速移动时头/耳不会抖成“锁头”。
- 连续工作 2 分钟时敲键盘、疲劳、烦躁插入无整图闪变。
- 拖动悬浮桌宠并释放后先站稳再恢复动作。
- 125% / 150% DPI 无明显像素撕裂和布局偏移。

- [ ] **Step 8: 仅在 Step 1~7 全通过后更新 PR 验证证据；PR 仍保持 Draft，直到用户接受实机观感**

---

## Plan Self-Review

- **Spec coverage:** v2 spec 的独立 Raster Skeleton、60Hz 连续 Motion、Animation Graph、IK、Spring、走跑跳、工作/疲劳/烦躁、Pointer 层级响应、Floating Pet、DPI、fail-closed asset、CI/Release/实机验收均有对应任务。
- **Placeholder scan:** 无 TBD/TODO/“later”；所有关键接口、路径、测试命令和验收条件均明确。
- **Type consistency:** `MaotaiMotionEngine.Update(double, MaotaiMotionInput) -> MaotaiPoseFrame` 是 Task 4 之后统一的数据通路；Task 5 Renderer 只消费 `MaotaiPoseFrame`；Task 6 Render Loop 只调用这两个接口。
- **Risk isolation:** v2 在独立分支 `feature/maotai-natural-motion-v2` 实施，不移动已通过 v1.3 Release Gate 的 Draft PR head，直到 v2 自己通过回归门槛。
