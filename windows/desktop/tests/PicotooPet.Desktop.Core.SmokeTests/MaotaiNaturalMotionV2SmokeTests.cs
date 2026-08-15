using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 的无撕裂、连续渲染与自然运动合同。</summary>
internal static class MaotaiNaturalMotionV2SmokeTests
{
    /// <summary>先验证纯数学和状态图，再验证当前可见渲染路径。</summary>
    public static void Run()
    {
        VerifyMotionMathContracts();
        VerifyAnimationGraphContracts();
        VerifyLocomotionContracts();
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
        var update = type!.GetMethod("Update", BindingFlags.Instance | BindingFlags.Public);
        var position = type.GetProperty("PositionX", BindingFlags.Instance | BindingFlags.Public);
        var velocity = type.GetProperty("VelocityX", BindingFlags.Instance | BindingFlags.Public);
        var gait = type.GetProperty("GaitPhase", BindingFlags.Instance | BindingFlags.Public);
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

        Assert(
            !xaml.Contains("<Image.Clip>", StringComparison.Ordinal),
            "v2 可见茅台禁止从完整角色图 Clip 裁出头/爪/尾；该结构会产生撕裂和重影");
        Assert(
            code.Contains("CompositionTarget.Rendering", StringComparison.Ordinal),
            "v2 必须由 CompositionTarget.Rendering 连续推进姿态");
        Assert(
            !code.Contains("Interval = TimeSpan.FromMilliseconds(220)", StringComparison.Ordinal),
            "v2 禁止 220ms DispatcherTimer 作为运动主时钟");
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
