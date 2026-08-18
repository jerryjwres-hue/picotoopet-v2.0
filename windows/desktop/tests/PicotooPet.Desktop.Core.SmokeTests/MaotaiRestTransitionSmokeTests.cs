using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台坐下、趴下、睡眠、醒来和起身的合法连续过渡链。</summary>
internal static class MaotaiRestTransitionSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var stateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var graphType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAnimationGraph");
        var request   = graphType.GetMethod("Request", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 Request");
        var update = graphType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 Update");
        var active = graphType.GetProperty("ActiveState", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 ActiveState");

        var idle         = Enum.Parse(stateType, "Idle");
        var sleep        = Enum.Parse(stateType, "Sleep");
        var userReaction = Enum.Parse(stateType, "UserReaction");
        var graph        = Activator.CreateInstance(graphType, idle)
            ?? throw new InvalidOperationException("无法创建休息 AnimationGraph");

        request.Invoke(graph, [sleep]);
        var sleepChain = CaptureUntil(
            graph,
            update,
            active,
            terminalState: "Sleep",
            maxFrames: 300);
        AssertSequence(
            sleepChain,
            ["Sit", "LieDown", "Sleep"],
            "Idle -> Sleep 必须经过 Sit / LieDown，禁止姿态硬切");

        request.Invoke(graph, [idle]);
        var wakeChain = CaptureUntil(
            graph,
            update,
            active,
            terminalState: "Idle",
            maxFrames: 300);
        AssertSequence(
            wakeChain,
            ["Wake", "GetUp", "Idle"],
            "Sleep -> Idle 必须经过 Wake / GetUp，禁止瞬间起身");

        var interactionGraph = Activator.CreateInstance(graphType, sleep)
            ?? throw new InvalidOperationException("无法创建睡眠交互 AnimationGraph");
        request.Invoke(interactionGraph, [userReaction]);
        var interactionWakeChain = CaptureUntil(
            interactionGraph,
            update,
            active,
            terminalState: "UserReaction",
            maxFrames: 300);
        AssertSequence(
            interactionWakeChain,
            ["Wake", "GetUp", "UserReaction"],
            "睡着时被摸/点击必须先 Wake -> GetUp，再进入 UserReaction，禁止 Sleep 硬切互动姿态");

        VerifyWakeGetUpPoseContinuity();
    }

    /// <summary>状态链合法还不够；Wake 最后一帧切到 GetUp 第一帧时身体高度与纵向缩放都必须连续。</summary>
    private static void VerifyWakeGetUpPoseContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = engineType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("MotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, 509, 72.0)
            ?? throw new InvalidOperationException("无法创建醒来连续性 Motion Engine");

        object? previousPose = null;
        var stableSleepFrames = 0;
        for (var frame = 0; frame < 420; frame++)
        {
            previousPose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput("Sleep")])
                ?? throw new InvalidOperationException("睡眠预热没有输出 Pose");
            if (ReadString(previousPose, "MotionState") == "Sleep")
            {
                stableSleepFrames++;
                if (stableSleepFrames >= 30)
                {
                    break;
                }
            }
            else
            {
                stableSleepFrames = 0;
            }
        }

        Assert(stableSleepFrames >= 30, "醒来连续性测试未能稳定进入 Sleep");

        var previousState = ReadString(previousPose!, "MotionState");
        var sawBoundary = false;
        var wakeBodyY = 0.0;
        var getUpBodyY = 0.0;
        var bodyYDelta = double.PositiveInfinity;
        var wakeScaleY = 0.0;
        var getUpScaleY = 0.0;
        var scaleYDelta = double.PositiveInfinity;

        for (var frame = 0; frame < 300; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(null)])
                ?? throw new InvalidOperationException("醒来连续性测试没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (previousState == "Wake" && state == "GetUp")
            {
                wakeBodyY = ReadBodyValue(previousPose!, "Y");
                getUpBodyY = ReadBodyValue(pose, "Y");
                bodyYDelta = Math.Abs(getUpBodyY - wakeBodyY);
                wakeScaleY = ReadBodyValue(previousPose!, "ScaleY");
                getUpScaleY = ReadBodyValue(pose, "ScaleY");
                scaleYDelta = Math.Abs(getUpScaleY - wakeScaleY);
                sawBoundary = true;
                break;
            }

            previousPose = pose;
            previousState = state;
        }

        Assert(sawBoundary, "醒来连续性测试未观察到 Wake -> GetUp 边界");
        Assert(bodyYDelta < 0.75,
            $"Wake -> GetUp 身体高度不能出现可见跳帧；delta={bodyYDelta:F3}, wakeY={wakeBodyY:F3}, getUpY={getUpBodyY:F3}");
        Assert(scaleYDelta < 0.012,
            $"Wake -> GetUp 身体纵向缩放不能突然压缩；delta={scaleYDelta:F4}, wakeScaleY={wakeScaleY:F4}, getUpScaleY={getUpScaleY:F4}");
    }

    private static object CreateRestingInput(string? autonomousState)
    {
        var baseType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var input = Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, "Resting"),
            0.0,
            0.0,
            false,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            72.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 Resting MotionInput");

        if (autonomousState is not null)
        {
            var motionStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
            RequireProperty(inputType, "AutonomousState").SetValue(
                input,
                Enum.Parse(motionStateType, autonomousState));
        }

        return input;
    }

    private static double ReadBodyValue(object pose, string propertyName)
    {
        var body = RequireProperty(pose.GetType(), "Body").GetValue(pose)
            ?? throw new InvalidOperationException("Pose.Body 为空");
        return (double)(RequireProperty(body.GetType(), propertyName).GetValue(body)
            ?? throw new InvalidOperationException($"Pose.Body.{propertyName} 为空"));
    }

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static List<string> CaptureUntil(
        object graph,
        MethodInfo update,
        PropertyInfo active,
        string terminalState,
        int maxFrames)
    {
        var states = new List<string>(8);
        var last   = string.Empty;

        for (var frame = 0; frame < maxFrames; frame++)
        {
            var state = active.GetValue(graph)?.ToString() ?? string.Empty;
            if (!string.Equals(state, last, StringComparison.Ordinal))
            {
                states.Add(state);
                last = state;
            }

            if (string.Equals(state, terminalState, StringComparison.Ordinal))
            {
                return states;
            }

            update.Invoke(graph, [1.0 / 60.0]);
        }

        throw new InvalidOperationException($"AnimationGraph 未在 {maxFrames} 帧内到达 {terminalState}");
    }

    private static void AssertSequence(
        IReadOnlyList<string> actual,
        IReadOnlyList<string> expected,
        string message)
    {
        var searchIndex = 0;
        foreach (var state in actual)
        {
            if (searchIndex < expected.Count &&
                string.Equals(state, expected[searchIndex], StringComparison.Ordinal))
            {
                searchIndex++;
            }
        }

        if (searchIndex != expected.Count)
        {
            throw new InvalidOperationException(
                $"{message}; actual={string.Join(" -> ", actual)}");
        }
    }

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
