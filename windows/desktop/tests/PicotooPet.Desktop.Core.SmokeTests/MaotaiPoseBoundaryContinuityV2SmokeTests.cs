using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结相邻 AnimationGraph 节点的真实 Pose 连续性；合法状态链不能用一帧弹回中性姿态来连接。</summary>
internal static class MaotaiPoseBoundaryContinuityV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifySitLieDownSleepBoundaries();
        VerifyWorkSettleTypingBoundary();
        VerifyWorkCycleBoundaries();
    }

    private static void VerifySitLieDownSleepBoundaries()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 701, 72.0)
            ?? throw new InvalidOperationException("无法创建休息边界 Motion Engine");
        var input      = CreateInput("Resting", 72.0, 72.0, autonomousState: "Sleep");

        object? previousPose = null;
        var previousState    = string.Empty;
        var sawSitLieDown    = false;
        var sawLieDownSleep  = false;

        for (var frame = 0; frame < 420; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("休息边界测试没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (previousPose is not null && previousState == "Sit" && state == "LieDown")
            {
                AssertBodyBoundary(previousPose, pose, "Sit→LieDown", maxYDelta: 0.85, maxScaleYDelta: 0.015);
                sawSitLieDown = true;
            }

            if (previousPose is not null && previousState == "LieDown" && state == "Sleep")
            {
                AssertBodyBoundary(previousPose, pose, "LieDown→Sleep", maxYDelta: 0.85, maxScaleYDelta: 0.015);
                sawLieDownSleep = true;
                break;
            }

            previousPose  = pose;
            previousState = state;
        }

        Assert(sawSitLieDown, "休息边界测试未观察到 Sit→LieDown");
        Assert(sawLieDownSleep, "休息边界测试未观察到 LieDown→Sleep");
    }

    private static void VerifyWorkSettleTypingBoundary()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 709, 28.0)
            ?? throw new InvalidOperationException("无法创建工作边界 Motion Engine");
        var input      = CreateInput("Working", 108.0, 108.0, autonomousState: null);

        object? previousPose = null;
        var previousState    = string.Empty;
        var sawBoundary      = false;

        for (var frame = 0; frame < 900; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("工作边界测试没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (previousPose is not null && previousState == "WorkSettle" && state == "WorkTyping")
            {
                AssertBodyBoundary(previousPose, pose, "WorkSettle→WorkTyping", maxYDelta: 0.75, maxScaleYDelta: 0.010);

                var pawDelta = BoneDistance(previousPose, pose, "FrontLeftPaw");
                Assert(pawDelta < 1.50,
                    $"WorkSettle→WorkTyping 左前爪不能瞬移到键盘；delta={pawDelta:F3}");
                sawBoundary = true;
                break;
            }

            previousPose  = pose;
            previousState = state;
        }

        Assert(sawBoundary, "工作边界测试未观察到 WorkSettle→WorkTyping");
    }

    private static void VerifyWorkCycleBoundaries()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 719, 108.0)
            ?? throw new InvalidOperationException("无法创建完整工作循环 Motion Engine");
        var input      = CreateInput("Working", 108.0, 108.0, autonomousState: null);

        (string From, string To, string Label)[] expectedBoundaries =
        [
            ("WorkTyping", "WorkTired", "WorkTyping→WorkTired"),
            ("WorkTired", "Yawn", "WorkTired→Yawn"),
            ("Yawn", "WorkTyping", "Yawn→WorkTyping"),
            ("WorkTyping", "WorkAnnoyed", "WorkTyping→WorkAnnoyed"),
            ("WorkAnnoyed", "Recover", "WorkAnnoyed→Recover"),
            ("Recover", "WorkTyping", "Recover→WorkTyping"),
        ];

        object? previousPose = null;
        var previousState    = string.Empty;
        var boundaryIndex    = 0;

        for (var frame = 0; frame < 2100 && boundaryIndex < expectedBoundaries.Length; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("完整工作循环边界测试没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (previousPose is not null && previousState != state)
            {
                var expected = expectedBoundaries[boundaryIndex];
                if (previousState == expected.From && state == expected.To)
                {
                    AssertBodyBoundary(
                        previousPose,
                        pose,
                        expected.Label,
                        maxYDelta: 0.75,
                        maxScaleYDelta: 0.012);

                    var leftPawDelta  = BoneDistance(previousPose, pose, "FrontLeftPaw");
                    var rightPawDelta = BoneDistance(previousPose, pose, "FrontRightPaw");
                    Assert(leftPawDelta < 1.60,
                        $"{expected.Label} 左前爪出现节点瞬移；delta={leftPawDelta:F3}");
                    Assert(rightPawDelta < 1.60,
                        $"{expected.Label} 右前爪出现节点瞬移；delta={rightPawDelta:F3}");
                    boundaryIndex++;
                }
            }

            previousPose  = pose;
            previousState = state;
        }

        Assert(boundaryIndex == expectedBoundaries.Length,
            $"完整工作循环只观察到 {boundaryIndex}/{expectedBoundaries.Length} 个连续性边界");
    }

    private static void AssertBodyBoundary(
        object previousPose,
        object pose,
        string label,
        double maxYDelta,
        double maxScaleYDelta)
    {
        var bodyYDelta = Math.Abs(
            ReadBoneDouble(pose, "Body", "Y") -
            ReadBoneDouble(previousPose, "Body", "Y"));
        var scaleYDelta = Math.Abs(
            ReadBoneDouble(pose, "Body", "ScaleY") -
            ReadBoneDouble(previousPose, "Body", "ScaleY"));

        Assert(bodyYDelta < maxYDelta,
            $"{label} 身体高度出现节点跳帧；delta={bodyYDelta:F3}");
        Assert(scaleYDelta < maxScaleYDelta,
            $"{label} 身体纵向缩放出现节点跳帧；delta={scaleYDelta:F4}");
    }

    private static double BoneDistance(
        object previousPose,
        object pose,
        string boneName)
    {
        var dx = ReadBoneDouble(pose, boneName, "X") -
            ReadBoneDouble(previousPose, boneName, "X");
        var dy = ReadBoneDouble(pose, boneName, "Y") -
            ReadBoneDouble(previousPose, boneName, "Y");
        return Math.Sqrt((dx * dx) + (dy * dy));
    }

    private static object CreateInput(
        string baseState,
        double targetX,
        double workAnchorX,
        string? autonomousState)
    {
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var baseStateType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var input = Activator.CreateInstance(
            inputType,
            [
                Enum.Parse(baseStateType, baseState),
                0.0,
                0.0,
                false,
                Enum.Parse(interactionType, "None"),
                18.0,
                150.0,
                targetX,
                false,
                false,
                workAnchorX,
            ]) ?? throw new InvalidOperationException("无法创建边界连续性 MotionInput");

        if (autonomousState is not null)
        {
            var motionStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
            RequireProperty(inputType, "AutonomousState").SetValue(
                input,
                Enum.Parse(motionStateType, autonomousState));
        }

        return input;
    }

    private static double ReadBoneDouble(object pose, string boneName, string propertyName)
    {
        var bone = RequireProperty(pose.GetType(), boneName).GetValue(pose)
            ?? throw new InvalidOperationException($"Pose.{boneName} 为空");
        return Convert.ToDouble(
            RequireProperty(bone.GetType(), propertyName).GetValue(bone),
            System.Globalization.CultureInfo.InvariantCulture);
    }

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static Type RequireType(string name) =>
        DesktopAssembly.GetType(name, throwOnError: true)!;

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
