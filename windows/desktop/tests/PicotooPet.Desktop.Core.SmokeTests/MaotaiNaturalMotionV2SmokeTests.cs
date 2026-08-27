using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 的连续运动、无撕裂和自然行为合同。</summary>
internal static class MaotaiNaturalMotionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyMathCore();
        VerifyAnimationGraph();
        VerifyLocomotion();
        VerifyMotionEngineBasics();
        VerifyRasterSkeleton();
        VerifyContinuousRenderPath();
        VerifyNaturalWorkBehavior();
        VerifyStrongStatePriority();
    }

    private static void VerifyMathCore()
    {
        var springType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiSpring");
        var spring     = Activator.CreateInstance(springType, 0.0, 0.0, 5.5, 0.82)
            ?? throw new InvalidOperationException("无法创建 MaotaiSpring");
        var step       = RequireMethod(springType, "Step");
        var value      = RequireProperty(springType, "Value");

        for (var index = 0; index < 120; index++)
        {
            step.Invoke(spring, [10.0, 1.0 / 60.0]);
        }

        var settled = (double)value.GetValue(spring)!;
        Assert(double.IsFinite(settled), "MaotaiSpring 产生 NaN/Infinity");
        Assert(Math.Abs(settled - 10.0) < 0.05, "MaotaiSpring 在 2 秒内没有稳定收敛");

        var ikType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiIkSolver");
        var solve    = RequireMethod(ikType, "SolveTwoBone", isStatic: true);
        var solution = solve.Invoke(null, [0.0, 0.0, 30.0, 26.0, 38.0, 20.0, 1])
            ?? throw new InvalidOperationException("MaotaiIkSolver 没有返回解");
        var endError = ReadDouble(solution, "EndError");

        Assert(double.IsFinite(endError) && endError < 0.01, "可达 IK 末端误差过大");
    }

    private static void VerifyAnimationGraph()
    {
        var stateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var graphType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAnimationGraph");
        var request   = RequireMethod(graphType, "Request");
        var active    = RequireProperty(graphType, "ActiveState");
        var target    = RequireProperty(graphType, "TargetState");

        var idle    = Enum.Parse(stateType, "Idle");
        var jumpAir = Enum.Parse(stateType, "JumpAir");
        var graph   = Activator.CreateInstance(graphType, idle)
            ?? throw new InvalidOperationException("无法创建 MaotaiAnimationGraph");
        request.Invoke(graph, [jumpAir]);
        Assert(
            string.Equals(active.GetValue(graph)?.ToString(), "JumpPrep", StringComparison.Ordinal),
            "Jump 必须先进入 JumpPrep，禁止 Idle -> JumpAir 瞬切");

        var run      = Enum.Parse(stateType, "Run");
        var sleep    = Enum.Parse(stateType, "Sleep");
        var runGraph = Activator.CreateInstance(graphType, run)
            ?? throw new InvalidOperationException("无法创建 Run AnimationGraph");
        request.Invoke(runGraph, [sleep]);
        Assert(
            !string.Equals(target.GetValue(runGraph)?.ToString(), "Sleep", StringComparison.Ordinal),
            "Run 禁止瞬间硬切 Sleep");
    }

    private static void VerifyLocomotion()
    {
        var type       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLocomotionController");
        var controller = Activator.CreateInstance(type, 50.0)
            ?? throw new InvalidOperationException("无法创建 MaotaiLocomotionController");
        var update     = RequireMethod(type, "Update");
        var position   = RequireProperty(type, "PositionX");
        var velocity   = RequireProperty(type, "VelocityX");
        var gait       = RequireProperty(type, "GaitPhase");

        for (var frame = 0; frame < 600; frame++)
        {
            var targetX = frame < 300 ? 130.0 : 30.0;
            update.Invoke(
                controller,
                [1.0 / 60.0, targetX, frame < 180, frame == 360, 20.0, 140.0]);

            var x = (double)position.GetValue(controller)!;
            var v = (double)velocity.GetValue(controller)!;
            var p = (double)gait.GetValue(controller)!;
            Assert(double.IsFinite(x) && double.IsFinite(v) && double.IsFinite(p),
                "Locomotion 600 帧模拟出现 NaN/Infinity");
            Assert(x >= 19.99 && x <= 140.01, "Locomotion 越过舞台边界");
        }
    }

    private static void VerifyMotionEngineBasics()
    {
        var engineType      = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update          = RequireMethod(engineType, "Update");
        var firstEngine     = Activator.CreateInstance(engineType, 17, 50.0)
            ?? throw new InvalidOperationException("无法创建第一个 Motion Engine");
        var secondEngine    = Activator.CreateInstance(engineType, 17, 50.0)
            ?? throw new InvalidOperationException("无法创建第二个 Motion Engine");
        var supportRun      = false;
        var supportStartX   = 0.0;
        var supportStartY   = 0.0;
        var maxSupportDrift = 0.0;

        for (var frame = 0; frame < 360; frame++)
        {
            var input = CreateInput(
                baseState: "Resting",
                interaction: "None",
                targetX: frame < 180 ? 128.0 : 32.0,
                wantsRun: frame is >= 75 and < 145,
                wantsJump: frame == 215,
                workAnchorX: 108.0,
                pointerX: Math.Sin(frame * 0.045),
                pointerY: Math.Cos(frame * 0.033) * 0.55,
                pointerInside: frame % 120 < 90);

            var first  = update.Invoke(firstEngine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("Motion Engine 没有输出 PoseFrame");
            var second = update.Invoke(secondEngine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("Motion Engine 没有输出第二个 PoseFrame");

            Assert(first.Equals(second), "相同 seed + 输入序列必须产生完全确定的 Pose");
            AssertPoseFinite(first, "Root");
            AssertPoseFinite(first, "Head");
            AssertPoseFinite(first, "TailTip");
            AssertPoseFinite(first, "FrontLeftPaw");

            var support = ReadBool(first, "FrontLeftSupport");
            var pawX    = ReadDouble(first, "FrontLeftPawWorldX");
            var pawY    = ReadDouble(first, "FrontLeftPawWorldY");
            if (support)
            {
                if (!supportRun)
                {
                    supportRun    = true;
                    supportStartX = pawX;
                    supportStartY = pawY;
                }
                else
                {
                    var dx = pawX - supportStartX;
                    var dy = pawY - supportStartY;
                    maxSupportDrift = Math.Max(maxSupportDrift, Math.Sqrt((dx * dx) + (dy * dy)));
                }
            }
            else
            {
                supportRun = false;
            }
        }

        Assert(maxSupportDrift < 0.75, "Walk 支撑相脚掌世界漂移过大，会产生滑步感");
    }

    private static void VerifyRasterSkeleton()
    {
        var manifestType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest");
        _ = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer");
        var isKnown = RequireMethod(manifestType, "IsKnownAsset", isStatic: true);

        string[] requiredAssets =
        [
            "torso_neutral.png", "head.png", "ear_left.png", "ear_right.png",
            "eye_left_open.png", "eye_right_open.png", "pupil_left.png", "pupil_right.png",
            "mouth_smile.png", "front_left_upper.png", "front_left_lower.png", "front_left_paw.png",
            "front_right_upper.png", "front_right_lower.png", "front_right_paw.png",
            "hind_left_upper.png", "hind_left_lower.png", "hind_left_paw.png",
            "hind_right_upper.png", "hind_right_lower.png", "hind_right_paw.png",
            "tail_base.png", "tail_mid.png", "tail_tip.png",
            "headphone_band.png", "headphone_left.png", "headphone_right.png",
            "laptop.png", "drink.png", "shadow.png",
        ];

        foreach (var asset in requiredAssets)
        {
            Assert((bool)isKnown.Invoke(null, [asset])!, $"v2 白名单缺少独立资产 {asset}");
        }

        Assert(!(bool)isKnown.Invoke(null, ["../head.png"])!, "v2 白名单不得接受 .. 路径");
        Assert(!(bool)isKnown.Invoke(null, ["head/evil.png"])!, "v2 白名单不得接受路径分隔符");
    }

    private static void VerifyContinuousRenderPath()
    {
        var root   = FindRepositoryRoot();
        var xaml   = ReadSource(root, "AssistantPetPanel.xaml");
        var code   = ReadSource(root, "AssistantPetPanel.Maotai.cs");
        var loader = ReadSource(root, "MaotaiPetAssetLoader.cs");

        Assert(!xaml.Contains("<Image.Clip>", StringComparison.Ordinal),
            "v2 可见茅台禁止从完整角色图 Clip 裁头/爪/尾");
        Assert(xaml.Contains("x:Name=\"MaotaiV2Root\"", StringComparison.Ordinal),
            "v2 缺少独立 Raster Skeleton 根层");
        Assert(xaml.Contains("x:Name=\"MaotaiV2FrontLeftPaw\"", StringComparison.Ordinal),
            "v2 缺少独立 Paw 图层");
        Assert(code.Contains("CompositionTarget.Rendering", StringComparison.Ordinal),
            "v2 必须使用显示器连续 Render Loop");
        Assert(!code.Contains("_maotaiTimer", StringComparison.Ordinal),
            "v2 运动主路径不得残留低频 DispatcherTimer");
        Assert(code.Contains("MaotaiMaximumDeltaSeconds = 0.05", StringComparison.Ordinal),
            "v2 必须裁剪长帧 deltaTime，禁止卡顿后补帧瞬移");
        Assert(loader.Contains("V2AssetRoot", StringComparison.Ordinal) &&
               loader.Contains("\"maotai\"", StringComparison.Ordinal) &&
               loader.Contains("\"v2\"", StringComparison.Ordinal),
            "v2 资产必须来自固定应用 UI 目录 maotai/v2");
    }

    private static void VerifyNaturalWorkBehavior()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 29, 28.0)
            ?? throw new InvalidOperationException("无法创建工作行为 Motion Engine");

        var firstTypingX = double.NaN;
        var typingSamples = 0;
        var leftMin  = double.PositiveInfinity;
        var leftMax  = double.NegativeInfinity;
        var rightMin = double.PositiveInfinity;
        var rightMax = double.NegativeInfinity;
        var sawTired    = false;
        var sawYawn     = false;
        var sawAnnoyed  = false;
        var sawRecover  = false;

        for (var frame = 0; frame < 2100; frame++)
        {
            var input = CreateInput(
                baseState: "Working",
                interaction: "None",
                targetX: 108.0,
                wantsRun: false,
                wantsJump: false,
                workAnchorX: 108.0,
                pointerX: 0.15,
                pointerY: -0.05,
                pointerInside: true);
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("工作行为没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (state == "WorkTyping")
            {
                var x = ReadDouble(pose, "StageX");
                if (double.IsNaN(firstTypingX))
                {
                    firstTypingX = x;
                }

                var leftY  = ReadPoseDouble(pose, "FrontLeftPaw", "Y");
                var rightY = ReadPoseDouble(pose, "FrontRightPaw", "Y");
                leftMin    = Math.Min(leftMin, leftY);
                leftMax    = Math.Max(leftMax, leftY);
                rightMin   = Math.Min(rightMin, rightY);
                rightMax   = Math.Max(rightMax, rightY);
                typingSamples++;
            }

            sawTired   |= state == "WorkTired";
            sawYawn    |= state == "Yawn";
            sawAnnoyed |= state == "WorkAnnoyed";
            sawRecover |= state == "Recover";
        }

        Assert(!double.IsNaN(firstTypingX), "Working 最终没有进入 WorkTyping");
        Assert(Math.Abs(firstTypingX - 108.0) <= 5.0,
            "茅台还没走到电脑锚点就开始敲键盘，动作会显得瞬移/割裂");
        Assert(typingSamples >= 60, "WorkTyping 连续采样不足");
        Assert(leftMax - leftMin >= 1.0 && rightMax - rightMin >= 1.0,
            "左右前爪没有连续键盘按压行程，仍像静态图");
        Assert(sawTired && sawYawn && sawAnnoyed && sawRecover,
            "工作循环必须自然出现疲劳、哈欠、烦躁与恢复，而不是整图硬切");

        var root = FindRepositoryRoot();
        var code = ReadSource(root, "AssistantPetPanel.Maotai.cs");
        Assert(!code.Contains("ApplyMaotaiSource", StringComparison.Ordinal) &&
               !code.Contains("_maotaiWorkingTired", StringComparison.Ordinal),
            "疲劳/烦躁禁止回退到整张角色图切换");
    }

    private static void VerifyStrongStatePriority()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 31, 72.0)
            ?? throw new InvalidOperationException("无法创建强状态优先级 Motion Engine");
        var input = CreateInput(
            baseState: "Offline",
            interaction: "Pat",
            targetX: 72.0,
            wantsRun: false,
            wantsJump: false,
            workAnchorX: 108.0,
            pointerX: 0.0,
            pointerY: 0.0,
            pointerInside: true);
        var pose = update.Invoke(engine, [1.0 / 60.0, input])
            ?? throw new InvalidOperationException("强状态测试没有输出 Pose");

        Assert(ReadString(pose, "MotionState") != "UserReaction",
            "Offline/Error 等真实强状态必须高于摸头/点击互动");
    }

    private static object CreateInput(
        string baseState,
        string interaction,
        double targetX,
        bool wantsRun,
        bool wantsJump,
        double workAnchorX,
        double pointerX,
        double pointerY,
        bool pointerInside)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
            pointerX,
            pointerY,
            pointerInside,
            Enum.Parse(interactionType, interaction),
            20.0,
            140.0,
            targetX,
            wantsRun,
            wantsJump,
            workAnchorX)
            ?? throw new InvalidOperationException("无法创建 MaotaiMotionInput");
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static MethodInfo RequireMethod(
        Type type,
        string name,
        bool isStatic = false)
    {
        var flags = BindingFlags.Public |
            (isStatic ? BindingFlags.Static : BindingFlags.Instance);
        return type.GetMethod(name, flags) ??
            throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");
    }

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static void AssertPoseFinite(object frame, string propertyName)
    {
        var pose = RequireProperty(frame.GetType(), propertyName).GetValue(frame)
            ?? throw new InvalidOperationException($"PoseFrame 缺少 {propertyName}");
        Assert(double.IsFinite(ReadDouble(pose, "X")), $"{propertyName}.X 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "Y")), $"{propertyName}.Y 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "RotationDeg")), $"{propertyName}.RotationDeg 非有限值");
    }

    private static double ReadPoseDouble(
        object frame,
        string poseProperty,
        string valueProperty)
    {
        var pose = RequireProperty(frame.GetType(), poseProperty).GetValue(frame)
            ?? throw new InvalidOperationException($"PoseFrame 缺少 {poseProperty}");
        return ReadDouble(pose, valueProperty);
    }

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static bool ReadBool(object value, string propertyName) =>
        (bool)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static string ReadSource(string root, string fileName) =>
        File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            fileName));

    private static string FindRepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory);
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        for (var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        throw new DirectoryNotFoundException("无法定位 PicotooPet 仓库根目录。");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
