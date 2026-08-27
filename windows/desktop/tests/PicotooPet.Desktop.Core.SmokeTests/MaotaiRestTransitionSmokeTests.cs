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
        VerifyDeferredUserReactionPoseContinuity();
    }

    /// <summary>状态链合法还不够；Sleep/Wake/GetUp 的真实相邻帧也不能出现身体、头部或耳朵跳变。</summary>
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
        var sawSleepWakeBoundary = false;
        var sleepBodyY = 0.0;
        var wakeStartBodyY = 0.0;
        var sleepWakeBodyYDelta = double.PositiveInfinity;
        var sleepScaleX = 0.0;
        var wakeStartScaleX = 0.0;
        var sleepWakeScaleXDelta = double.PositiveInfinity;
        var sleepScaleY = 0.0;
        var wakeStartScaleY = 0.0;
        var sleepWakeScaleYDelta = double.PositiveInfinity;
        var sleepHeadY = 0.0;
        var wakeStartHeadY = 0.0;
        var sleepWakeHeadYDelta = double.PositiveInfinity;
        var sleepLeftEarY = 0.0;
        var wakeStartLeftEarY = 0.0;
        var sleepWakeLeftEarYDelta = double.PositiveInfinity;
        var sawWakeGetUpBoundary = false;
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

            if (previousState == "Sleep" && state == "Wake")
            {
                sleepBodyY = ReadBodyValue(previousPose!, "Y");
                wakeStartBodyY = ReadBodyValue(pose, "Y");
                sleepWakeBodyYDelta = Math.Abs(wakeStartBodyY - sleepBodyY);
                sleepScaleX = ReadBodyValue(previousPose!, "ScaleX");
                wakeStartScaleX = ReadBodyValue(pose, "ScaleX");
                sleepWakeScaleXDelta = Math.Abs(wakeStartScaleX - sleepScaleX);
                sleepScaleY = ReadBodyValue(previousPose!, "ScaleY");
                wakeStartScaleY = ReadBodyValue(pose, "ScaleY");
                sleepWakeScaleYDelta = Math.Abs(wakeStartScaleY - sleepScaleY);
                sleepHeadY = ReadBoneValue(previousPose!, "Head", "Y");
                wakeStartHeadY = ReadBoneValue(pose, "Head", "Y");
                sleepWakeHeadYDelta = Math.Abs(wakeStartHeadY - sleepHeadY);
                sleepLeftEarY = ReadBoneValue(previousPose!, "LeftEar", "Y");
                wakeStartLeftEarY = ReadBoneValue(pose, "LeftEar", "Y");
                sleepWakeLeftEarYDelta = Math.Abs(wakeStartLeftEarY - sleepLeftEarY);
                sawSleepWakeBoundary = true;
            }

            if (previousState == "Wake" && state == "GetUp")
            {
                wakeBodyY = ReadBodyValue(previousPose!, "Y");
                getUpBodyY = ReadBodyValue(pose, "Y");
                bodyYDelta = Math.Abs(getUpBodyY - wakeBodyY);
                wakeScaleY = ReadBodyValue(previousPose!, "ScaleY");
                getUpScaleY = ReadBodyValue(pose, "ScaleY");
                scaleYDelta = Math.Abs(getUpScaleY - wakeScaleY);
                sawWakeGetUpBoundary = true;
                break;
            }

            previousPose = pose;
            previousState = state;
        }

        Assert(sawSleepWakeBoundary, "醒来连续性测试未观察到 Sleep -> Wake 边界");
        Assert(sleepWakeBodyYDelta < 0.75,
            $"Sleep -> Wake 身体高度不能出现可见跳帧；delta={sleepWakeBodyYDelta:F3}, sleepY={sleepBodyY:F3}, wakeY={wakeStartBodyY:F3}");
        Assert(sleepWakeScaleXDelta < 0.012,
            $"Sleep -> Wake 身体横向缩放不能突然收窄；delta={sleepWakeScaleXDelta:F4}, sleepScaleX={sleepScaleX:F4}, wakeScaleX={wakeStartScaleX:F4}");
        Assert(sleepWakeScaleYDelta < 0.012,
            $"Sleep -> Wake 身体纵向缩放不能突然拉长；delta={sleepWakeScaleYDelta:F4}, sleepScaleY={sleepScaleY:F4}, wakeScaleY={wakeStartScaleY:F4}");
        Assert(sleepWakeHeadYDelta < 0.45,
            $"Sleep -> Wake 头部高度必须由 spring 平滑承接；delta={sleepWakeHeadYDelta:F3}, sleepHeadY={sleepHeadY:F3}, wakeHeadY={wakeStartHeadY:F3}");
        Assert(sleepWakeLeftEarYDelta < 0.75,
            $"Sleep -> Wake 耳朵高度不能瞬间弹起；delta={sleepWakeLeftEarYDelta:F3}, sleepEarY={sleepLeftEarY:F3}, wakeEarY={wakeStartLeftEarY:F3}");
        Assert(sawWakeGetUpBoundary, "醒来连续性测试未观察到 Wake -> GetUp 边界");
        Assert(bodyYDelta < 0.75,
            $"Wake -> GetUp 身体高度不能出现可见跳帧；delta={bodyYDelta:F3}, wakeY={wakeBodyY:F3}, getUpY={getUpBodyY:F3}");
        Assert(scaleYDelta < 0.012,
            $"Wake -> GetUp 身体纵向缩放不能突然压缩；delta={scaleYDelta:F4}, wakeScaleY={wakeScaleY:F4}, getUpScaleY={getUpScaleY:F4}");
    }

    /// <summary>真实 Pat 脉冲结束后，延迟互动从 GetUp 接到 UserReaction 的首帧也必须保持骨骼连续。</summary>
    private static void VerifyDeferredUserReactionPoseContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = engineType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("MotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, 521, 72.0)
            ?? throw new InvalidOperationException("无法创建延迟互动连续性 Motion Engine");

        object? previousPose = null;
        var stableSleepFrames = 0;
        for (var frame = 0; frame < 420; frame++)
        {
            previousPose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput("Sleep")])
                ?? throw new InvalidOperationException("延迟互动测试的睡眠预热没有输出 Pose");
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

        Assert(stableSleepFrames >= 30, "延迟互动连续性测试未能稳定进入 Sleep");

        var previousState = ReadString(previousPose!, "MotionState");
        var sawBoundary = false;

        void ObserveBoundary(object pose)
        {
            var state = ReadString(pose, "MotionState");
            if (!sawBoundary && previousState == "GetUp" && state == "UserReaction")
            {
                var bodyYDelta = Math.Abs(
                    ReadBodyValue(pose, "Y") - ReadBodyValue(previousPose!, "Y"));
                var scaleXDelta = Math.Abs(
                    ReadBodyValue(pose, "ScaleX") - ReadBodyValue(previousPose!, "ScaleX"));
                var scaleYDelta = Math.Abs(
                    ReadBodyValue(pose, "ScaleY") - ReadBodyValue(previousPose!, "ScaleY"));
                var headDelta = BoneDistance(previousPose!, pose, "Head");
                var leftPawDelta = BoneDistance(previousPose!, pose, "FrontLeftPaw");
                var rightPawDelta = BoneDistance(previousPose!, pose, "FrontRightPaw");

                Assert(bodyYDelta < 0.75,
                    $"GetUp -> UserReaction 身体高度出现节点跳帧；delta={bodyYDelta:F3}");
                Assert(scaleXDelta < 0.012,
                    $"GetUp -> UserReaction 身体横向缩放出现硬切；delta={scaleXDelta:F4}");
                Assert(scaleYDelta < 0.012,
                    $"GetUp -> UserReaction 身体纵向缩放出现硬切；delta={scaleYDelta:F4}");
                Assert(headDelta < 0.75,
                    $"GetUp -> UserReaction 头部首帧位移过大；delta={headDelta:F3}");
                Assert(leftPawDelta < 1.25,
                    $"GetUp -> UserReaction 左前爪首帧瞬移；delta={leftPawDelta:F3}");
                Assert(rightPawDelta < 1.25,
                    $"GetUp -> UserReaction 右前爪首帧瞬移；delta={rightPawDelta:F3}");
                sawBoundary = true;
            }

            previousPose = pose;
            previousState = state;
        }

        // Real UI pulse       : Pat stays raw for 0.55 s (33 frames); if the mandatory wake chain is longer,
        // the engine's deferred latch must carry it until UserReaction without creating a pose seam.
        for (var frame = 0; frame < 33 && !sawBoundary; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(null, interaction: "Pat")])
                ?? throw new InvalidOperationException("延迟互动 Pat 脉冲没有输出 Pose");
            ObserveBoundary(pose);
        }

        for (var frame = 0; frame < 120 && !sawBoundary; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(null)])
                ?? throw new InvalidOperationException("Pat 脉冲过期后的延迟互动没有输出 Pose");
            ObserveBoundary(pose);
        }

        Assert(sawBoundary,
            "真实 0.55 秒 Pat 脉冲后没有观察到 GetUp -> UserReaction 相邻帧边界");
    }

    private static object CreateRestingInput(
        string? autonomousState,
        string interaction = "None")
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
            Enum.Parse(interactionType, interaction),
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

    private static double ReadBodyValue(object pose, string propertyName) =>
        ReadBoneValue(pose, "Body", propertyName);

    private static double BoneDistance(object previousPose, object pose, string boneName)
    {
        var dx = ReadBoneValue(pose, boneName, "X") - ReadBoneValue(previousPose, boneName, "X");
        var dy = ReadBoneValue(pose, boneName, "Y") - ReadBoneValue(previousPose, boneName, "Y");
        return Math.Sqrt((dx * dx) + (dy * dy));
    }

    private static double ReadBoneValue(object pose, string boneName, string propertyName)
    {
        var bone = RequireProperty(pose.GetType(), boneName).GetValue(pose)
            ?? throw new InvalidOperationException($"Pose.{boneName} 为空");
        return (double)(RequireProperty(bone.GetType(), propertyName).GetValue(bone)
            ?? throw new InvalidOperationException($"Pose.{boneName}.{propertyName} 为空"));
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
