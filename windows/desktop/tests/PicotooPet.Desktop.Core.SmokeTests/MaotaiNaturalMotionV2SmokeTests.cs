using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 的无撕裂、连续渲染与自然运动合同。</summary>
internal static class MaotaiNaturalMotionV2SmokeTests
{
    /// <summary>先验证纯数学、状态图、Motion Engine 与独立资产骨架，再验证可见渲染路径。</summary>
    public static void Run()
    {
        VerifyMotionMathContracts();
        VerifyAnimationGraphContracts();
        VerifyLocomotionContracts();
        VerifyMotionEngineContracts();
        VerifyRasterSkeletonContracts();
        VerifyVisibleRigContracts();
    }

    private static void VerifyMotionMathContracts()
    {
        var assembly   = typeof(AssistantPetPanel).Assembly;
        var springType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiSpring");
        Assert(springType is not null, "v2 缺少 MaotaiSpring 连续阻尼核心");

        var spring = Activator.CreateInstance(
            springType!,
            0.0,
            0.0,
            5.5,
            0.82);
        Assert(spring is not null, "无法创建 MaotaiSpring");

        var step = springType!.GetMethod(
            "Step",
            BindingFlags.Instance | BindingFlags.Public);
        var valueProperty = springType.GetProperty(
            "Value",
            BindingFlags.Instance | BindingFlags.Public);
        Assert(step is not null && valueProperty is not null, "MaotaiSpring API 不完整");

        for (var index = 0; index < 120; index++)
        {
            step!.Invoke(spring, [10.0, 1.0 / 60.0]);
        }

        var value = (double)valueProperty!.GetValue(spring!)!;
        Assert(double.IsFinite(value), "MaotaiSpring 产生 NaN/Infinity");
        Assert(Math.Abs(value - 10.0) < 0.05, "MaotaiSpring 在 2 秒内没有稳定收敛");

        var ikType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiIkSolver");
        Assert(ikType is not null, "v2 缺少 MaotaiIkSolver 两段 IK");
        var solve = ikType!.GetMethod(
            "SolveTwoBone",
            BindingFlags.Static | BindingFlags.Public);
        Assert(solve is not null, "MaotaiIkSolver 缺少 SolveTwoBone");

        var solution = solve!.Invoke(
            null,
            [0.0, 0.0, 30.0, 26.0, 38.0, 20.0, 1]);
        Assert(solution is not null, "MaotaiIkSolver 没有返回解");
        var errorProperty = solution!.GetType().GetProperty("EndError");
        Assert(errorProperty is not null, "IK 解缺少 EndError");
        var endError = (double)errorProperty!.GetValue(solution)!;
        Assert(double.IsFinite(endError) && endError < 0.01, "可达 IK 末端误差过大");
    }

    private static void VerifyAnimationGraphContracts()
    {
        var assembly  = typeof(AssistantPetPanel).Assembly;
        var stateType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var graphType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAnimationGraph");
        Assert(stateType is not null, "v2 缺少 MaotaiMotionState");
        Assert(graphType is not null, "v2 缺少 MaotaiAnimationGraph");

        var resolvedStateType = stateType!;
        var resolvedGraphType = graphType!;
        var idle               = Enum.Parse(resolvedStateType, "Idle");
        var jumpAir            = Enum.Parse(resolvedStateType, "JumpAir");
        var graph              = Activator.CreateInstance(resolvedGraphType, idle);
        Assert(graph is not null, "无法创建 MaotaiAnimationGraph");

        var request = resolvedGraphType.GetMethod(
            "Request",
            BindingFlags.Instance | BindingFlags.Public);
        var active = resolvedGraphType.GetProperty(
            "ActiveState",
            BindingFlags.Instance | BindingFlags.Public);
        var target = resolvedGraphType.GetProperty(
            "TargetState",
            BindingFlags.Instance | BindingFlags.Public);
        Assert(request is not null && active is not null && target is not null, "AnimationGraph API 不完整");

        request!.Invoke(graph, [jumpAir]);
        Assert(
            string.Equals(active!.GetValue(graph)?.ToString(), "JumpPrep", StringComparison.Ordinal),
            "Jump 必须先进入 JumpPrep 蓄力，禁止 Idle -> JumpAir 瞬切");

        var run      = Enum.Parse(resolvedStateType, "Run");
        var sleep    = Enum.Parse(resolvedStateType, "Sleep");
        var runGraph = Activator.CreateInstance(resolvedGraphType, run);
        Assert(runGraph is not null, "无法创建 Run AnimationGraph");
        request.Invoke(runGraph, [sleep]);
        Assert(
            !string.Equals(target!.GetValue(runGraph)?.ToString(), "Sleep", StringComparison.Ordinal),
            "Run 禁止瞬间硬切 Sleep；必须先减速并经过坐/趴过渡");
    }

    private static void VerifyLocomotionContracts()
    {
        var assembly = typeof(AssistantPetPanel).Assembly;
        var type = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLocomotionController");
        Assert(type is not null, "v2 缺少 MaotaiLocomotionController");

        var controller = Activator.CreateInstance(type!, 50.0);
        Assert(controller is not null, "无法创建 MaotaiLocomotionController");
        var update   = type!.GetMethod("Update", BindingFlags.Instance | BindingFlags.Public);
        var position = type.GetProperty("PositionX", BindingFlags.Instance | BindingFlags.Public);
        var velocity = type.GetProperty("VelocityX", BindingFlags.Instance | BindingFlags.Public);
        var gait     = type.GetProperty("GaitPhase", BindingFlags.Instance | BindingFlags.Public);
        Assert(update is not null && position is not null && velocity is not null && gait is not null,
            "Locomotion API 不完整");

        for (var frame = 0; frame < 600; frame++)
        {
            var targetX = frame < 300 ? 130.0 : 30.0;
            update!.Invoke(
                controller,
                [1.0 / 60.0, targetX, frame < 180, frame == 360, 20.0, 140.0]);

            var x = (double)position!.GetValue(controller!)!;
            var v = (double)velocity!.GetValue(controller)!;
            var p = (double)gait!.GetValue(controller)!;
            Assert(double.IsFinite(x) && double.IsFinite(v) && double.IsFinite(p),
                "Locomotion 600 帧模拟出现 NaN/Infinity");
            Assert(x >= 20.0 - 0.01 && x <= 140.0 + 0.01,
                "Locomotion 越过舞台边界");
        }
    }

    private static void VerifyMotionEngineContracts()
    {
        var assembly = typeof(AssistantPetPanel).Assembly;
        var baseStateType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var engineType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");

        Assert(baseStateType is not null, "v2 缺少 MaotaiBaseState 表现状态输入");
        Assert(interactionType is not null, "v2 缺少 MaotaiInteractionKind");
        Assert(inputType is not null, "v2 缺少 MaotaiMotionInput");
        Assert(engineType is not null, "v2 缺少 MaotaiMotionEngine");

        var resolvedBaseStateType   = baseStateType!;
        var resolvedInteractionType = interactionType!;
        var resolvedInputType       = inputType!;
        var resolvedEngineType      = engineType!;
        var resting                 = Enum.Parse(resolvedBaseStateType, "Resting");
        var none                    = Enum.Parse(resolvedInteractionType, "None");
        var firstEngine             = Activator.CreateInstance(resolvedEngineType, 17, 50.0);
        var secondEngine            = Activator.CreateInstance(resolvedEngineType, 17, 50.0);
        Assert(firstEngine is not null && secondEngine is not null, "无法创建确定性 Motion Engine");

        var update = resolvedEngineType.GetMethod(
            "Update",
            BindingFlags.Instance | BindingFlags.Public);
        Assert(update is not null, "MaotaiMotionEngine 缺少 Update");

        var supportRun      = false;
        var supportStartX   = 0.0;
        var supportStartY   = 0.0;
        var maxSupportDrift = 0.0;

        for (var frame = 0; frame < 360; frame++)
        {
            var targetX   = frame < 180 ? 128.0 : 32.0;
            var wantsRun  = frame is >= 75 and < 145;
            var wantsJump = frame == 215;
            var pointerX  = Math.Sin(frame * 0.045);
            var pointerY  = Math.Cos(frame * 0.033) * 0.55;
            var input = Activator.CreateInstance(
                resolvedInputType,
                resting,
                pointerX,
                pointerY,
                frame % 120 < 90,
                none,
                20.0,
                140.0,
                targetX,
                wantsRun,
                wantsJump,
                108.0);
            Assert(input is not null, "无法创建 MaotaiMotionInput");

            var firstFrame  = update!.Invoke(firstEngine, [1.0 / 60.0, input]);
            var secondFrame = update.Invoke(secondEngine, [1.0 / 60.0, input]);
            Assert(firstFrame is not null && secondFrame is not null, "Motion Engine 没有输出 PoseFrame");
            Assert(firstFrame!.Equals(secondFrame), "相同 seed + 输入序列必须产生完全确定的 Pose");

            AssertPoseFinite(firstFrame, "Root");
            AssertPoseFinite(firstFrame, "Head");
            AssertPoseFinite(firstFrame, "TailTip");
            AssertPoseFinite(firstFrame, "FrontLeftPaw");

            var support = ReadBool(firstFrame, "FrontLeftSupport");
            var pawX    = ReadDouble(firstFrame, "FrontLeftPawWorldX");
            var pawY    = ReadDouble(firstFrame, "FrontLeftPawWorldY");
            Assert(double.IsFinite(pawX) && double.IsFinite(pawY), "前左脚掌世界坐标不是有限值");

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

    private static void VerifyRasterSkeletonContracts()
    {
        var assembly = typeof(AssistantPetPanel).Assembly;
        var manifestType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest");
        var rendererType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer");
        Assert(manifestType is not null, "v2 缺少 MaotaiAssetManifest 独立部件白名单");
        Assert(rendererType is not null, "v2 缺少 MaotaiRasterRenderer");

        var isKnown = manifestType!.GetMethod(
            "IsKnownAsset",
            BindingFlags.Static | BindingFlags.Public);
        Assert(isKnown is not null, "MaotaiAssetManifest 缺少 IsKnownAsset");

        string[] requiredAssets =
        [
            "torso_neutral.png",
            "head.png",
            "ear_left.png",
            "ear_right.png",
            "eye_left_open.png",
            "eye_right_open.png",
            "pupil_left.png",
            "pupil_right.png",
            "mouth_smile.png",
            "front_left_upper.png",
            "front_left_lower.png",
            "front_left_paw.png",
            "front_right_upper.png",
            "front_right_lower.png",
            "front_right_paw.png",
            "hind_left_upper.png",
            "hind_left_lower.png",
            "hind_left_paw.png",
            "hind_right_upper.png",
            "hind_right_lower.png",
            "hind_right_paw.png",
            "tail_base.png",
            "tail_mid.png",
            "tail_tip.png",
            "headphone_band.png",
            "headphone_left.png",
            "headphone_right.png",
            "laptop.png",
            "drink.png",
            "shadow.png",
        ];

        foreach (var asset in requiredAssets)
        {
            Assert((bool)isKnown!.Invoke(null, [asset])!, $"v2 白名单缺少独立资产 {asset}");
        }

        Assert(!(bool)isKnown!.Invoke(null, ["../head.png"])!, "v2 资产白名单不得接受 .. 路径");
        Assert(!(bool)isKnown.Invoke(null, ["head/evil.png"])!, "v2 资产白名单不得接受路径分隔符");
    }

    private static void VerifyVisibleRigContracts()
    {
        var root = FindRepositoryRoot();
        var xaml = File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "AssistantPetPanel.xaml"));
        var code = File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "AssistantPetPanel.Maotai.cs"));
        var loader = File.ReadAllText(Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "MaotaiPetAssetLoader.cs"));

        Assert(
            !xaml.Contains("<Image.Clip>", StringComparison.Ordinal),
            "v2 可见茅台禁止从完整角色图 Clip 裁出头/爪/尾；该结构会产生撕裂和重影");
        Assert(xaml.Contains("x:Name=\"MaotaiV2Root\"", StringComparison.Ordinal),
            "v2 XAML 缺少独立 Raster Skeleton 根层");
        Assert(xaml.Contains("x:Name=\"MaotaiV2Torso\"", StringComparison.Ordinal),
            "v2 XAML 缺少独立 torso 图层");
        Assert(xaml.Contains("x:Name=\"MaotaiV2Head\"", StringComparison.Ordinal),
            "v2 XAML 缺少独立 head 图层");
        Assert(xaml.Contains("x:Name=\"MaotaiV2FrontLeftPaw\"", StringComparison.Ordinal),
            "v2 XAML 缺少独立 paw 图层");
        Assert(loader.Contains("\"maotai\",\n        \"v2\"", StringComparison.Ordinal),
            "v2 资产必须从固定应用 UI 目录 maotai/v2 加载");
        Assert(
            code.Contains("CompositionTarget.Rendering", StringComparison.Ordinal),
            "v2 必须由 CompositionTarget.Rendering 连续推进姿态");
        Assert(
            !code.Contains("Interval = TimeSpan.FromMilliseconds(220)", StringComparison.Ordinal),
            "v2 禁止 220ms DispatcherTimer 作为运动主时钟");
    }

    private static void AssertPoseFinite(object frame, string propertyName)
    {
        var pose = frame.GetType().GetProperty(propertyName)?.GetValue(frame);
        Assert(pose is not null, $"PoseFrame 缺少 {propertyName}");
        Assert(double.IsFinite(ReadDouble(pose!, "X")), $"{propertyName}.X 非有限值");
        Assert(double.IsFinite(ReadDouble(pose!, "Y")), $"{propertyName}.Y 非有限值");
        Assert(double.IsFinite(ReadDouble(pose!, "RotationDeg")), $"{propertyName}.RotationDeg 非有限值");
    }

    private static double ReadDouble(object value, string propertyName)
    {
        var property = value.GetType().GetProperty(propertyName);
        Assert(property is not null, $"缺少 double 属性 {propertyName}");
        return (double)property!.GetValue(value)!;
    }

    private static bool ReadBool(object value, string propertyName)
    {
        var property = value.GetType().GetProperty(propertyName);
        Assert(property is not null, $"缺少 bool 属性 {propertyName}");
        return (bool)property!.GetValue(value)!;
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        var current = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (current is not null)
        {
            if (Directory.Exists(Path.Combine(current.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(current.FullName, "pyproject.toml")))
            {
                return current.FullName;
            }

            current = current.Parent;
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
