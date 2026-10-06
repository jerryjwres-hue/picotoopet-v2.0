using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结待机生命感：眨眼、视线与睡眠微动必须来自 Motion Engine，不能靠整图状态帧。</summary>
internal static class MaotaiLifeMicroMotionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyIdleBlinking();
        VerifyOfflineEyesStayClosed();
        VerifyIdleGazeWanders();
        VerifyPointerOverridesAutonomousGaze();
        VerifySleepIgnoresPointerHover();
        VerifySleepTailSettles();
    }

    private static void VerifyIdleBlinking()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 101, 72.0)
            ?? throw new InvalidOperationException("无法创建待机生命感 Motion Engine");

        var sawHalf    = false;
        var sawClosed  = false;
        var openFrames = 0;

        for (var frame = 0; frame < 1200; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
                ?? throw new InvalidOperationException("待机生命感测试没有输出 Pose");
            var eye = ReadString(pose, "EyeState");
            sawHalf   |= eye == "Half";
            sawClosed |= eye == "Closed";
            openFrames += eye == "Open" ? 1 : 0;
        }

        Assert(sawHalf && sawClosed,
            "20 秒待机必须至少出现一次 Open -> Half -> Closed 的自然眨眼");
        Assert(openFrames > 960,
            "待机眨眼占比过高，会让茅台看起来困倦或机械");
    }

    private static void VerifyOfflineEyesStayClosed()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 101, 72.0)
            ?? throw new InvalidOperationException("无法创建 Offline Motion Engine");

        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Offline")])
                ?? throw new InvalidOperationException("Offline 测试没有输出 Pose");
            Assert(ReadString(pose, "EyeState") == "Closed",
                "Offline/Sleep 的真实状态优先级必须压过待机眨眼");
        }
    }

    private static void VerifyIdleGazeWanders()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 211, 72.0)
            ?? throw new InvalidOperationException("无法创建待机视线 Motion Engine");

        var minX = double.PositiveInfinity;
        var maxX = double.NegativeInfinity;
        var minY = double.PositiveInfinity;
        var maxY = double.NegativeInfinity;

        for (var frame = 0; frame < 720; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
                ?? throw new InvalidOperationException("待机视线测试没有输出 Pose");
            var pupil = RequireProperty(pose.GetType(), "LeftPupil").GetValue(pose)
                ?? throw new InvalidOperationException("LeftPupil 为空");
            var x = ReadDouble(pupil, "X");
            var y = ReadDouble(pupil, "Y");
            minX = Math.Min(minX, x);
            maxX = Math.Max(maxX, x);
            minY = Math.Min(minY, y);
            maxY = Math.Max(maxY, y);
        }

        Assert(maxX - minX > 0.8 || maxY - minY > 0.45,
            "12 秒待机瞳孔不能永远钉在正中央；需要缓慢自主视线游移");
    }

    private static void VerifyPointerOverridesAutonomousGaze()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 211, 72.0)
            ?? throw new InvalidOperationException("无法创建鼠标视线 Motion Engine");

        for (var frame = 0; frame < 240; frame++)
        {
            _ = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")]);
        }

        object? lastPose = null;
        for (var frame = 0; frame < 45; frame++)
        {
            lastPose = update.Invoke(
                engine,
                [1.0 / 60.0, CreateInput("Resting", pointerX: 1.0, pointerY: -1.0, pointerInside: true)]);
        }

        var pose = lastPose ?? throw new InvalidOperationException("鼠标视线测试没有输出 Pose");
        var pupil = RequireProperty(pose.GetType(), "LeftPupil").GetValue(pose)
            ?? throw new InvalidOperationException("LeftPupil 为空");
        Assert(ReadDouble(pupil, "X") > -4.5 && ReadDouble(pupil, "Y") < -2.6,
            "鼠标进入后必须覆盖自主视线，瞳孔应明确跟向用户指针");
    }

    /// <summary>鼠标只悬停不能惊动睡眠姿态；真正点击/摸头仍由交互链负责唤醒。</summary>
    private static void VerifySleepIgnoresPointerHover()
    {
        var engineType    = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update        = RequireMethod(engineType, "Update");
        var baselineEngine = Activator.CreateInstance(engineType, 401, 72.0)
            ?? throw new InvalidOperationException("无法创建 Sleep 基准 Motion Engine");
        var hoverEngine = Activator.CreateInstance(engineType, 401, 72.0)
            ?? throw new InvalidOperationException("无法创建 Sleep hover Motion Engine");

        for (var frame = 0; frame < 360; frame++)
        {
            _ = update.Invoke(
                baselineEngine,
                [1.0 / 60.0, CreateInput("Resting", autonomousState: "Sleep")]);
            _ = update.Invoke(
                hoverEngine,
                [1.0 / 60.0, CreateInput("Resting", autonomousState: "Sleep")]);
        }

        object? baselinePose = null;
        object? hoverPose = null;
        for (var frame = 0; frame < 120; frame++)
        {
            baselinePose = update.Invoke(
                baselineEngine,
                [1.0 / 60.0, CreateInput("Resting", autonomousState: "Sleep")]);
            hoverPose = update.Invoke(
                hoverEngine,
                [1.0 / 60.0, CreateInput(
                    "Resting",
                    pointerX: 1.0,
                    pointerY: -1.0,
                    pointerInside: true,
                    autonomousState: "Sleep")]);
        }

        var baseline = baselinePose ?? throw new InvalidOperationException("Sleep 基准没有输出 Pose");
        var hovered  = hoverPose ?? throw new InvalidOperationException("Sleep hover 没有输出 Pose");
        Assert(ReadString(baseline, "MotionState") == "Sleep" && ReadString(hovered, "MotionState") == "Sleep",
            "Sleep hover 测试必须在两条引擎路径都稳定进入 Sleep 后比较");

        var baselineHead = RequireProperty(baseline.GetType(), "Head").GetValue(baseline)
            ?? throw new InvalidOperationException("Sleep 基准 Head 为空");
        var hoveredHead = RequireProperty(hovered.GetType(), "Head").GetValue(hovered)
            ?? throw new InvalidOperationException("Sleep hover Head 为空");
        var baselineEar = RequireProperty(baseline.GetType(), "LeftEar").GetValue(baseline)
            ?? throw new InvalidOperationException("Sleep 基准 LeftEar 为空");
        var hoveredEar = RequireProperty(hovered.GetType(), "LeftEar").GetValue(hovered)
            ?? throw new InvalidOperationException("Sleep hover LeftEar 为空");

        var headXDelta = Math.Abs(ReadDouble(hoveredHead, "X") - ReadDouble(baselineHead, "X"));
        var headYDelta = Math.Abs(ReadDouble(hoveredHead, "Y") - ReadDouble(baselineHead, "Y"));
        var headRotationDelta = Math.Abs(
            ReadDouble(hoveredHead, "RotationDeg") - ReadDouble(baselineHead, "RotationDeg"));
        var earRotationDelta = Math.Abs(
            ReadDouble(hoveredEar, "RotationDeg") - ReadDouble(baselineEar, "RotationDeg"));

        Assert(headXDelta < 0.20 && headYDelta < 0.20 && headRotationDelta < 0.60 && earRotationDelta < 0.60,
            $"Sleep 时普通 hover 不应驱动头耳追踪；headX={headXDelta:F3}, headY={headYDelta:F3}, headRot={headRotationDelta:F3}, earRot={earRotationDelta:F3}");
    }

    /// <summary>睡眠保留轻微生命感，但尾巴不能继续沿用清醒 Resting 的高幅度摆动。</summary>
    private static void VerifySleepTailSettles()
    {
        var engineType  = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update      = RequireMethod(engineType, "Update");
        var idleEngine  = Activator.CreateInstance(engineType, 307, 72.0)
            ?? throw new InvalidOperationException("无法创建 Idle 尾巴基准 Motion Engine");
        var sleepEngine = Activator.CreateInstance(engineType, 307, 72.0)
            ?? throw new InvalidOperationException("无法创建 Sleep 尾巴 Motion Engine");

        var idleEnergy  = 0.0;
        var sleepEnergy = 0.0;
        var samples     = 0;
        var sawSleep    = false;

        for (var frame = 0; frame < 720; frame++)
        {
            var idlePose = update.Invoke(idleEngine, [1.0 / 60.0, CreateInput("Resting")])
                ?? throw new InvalidOperationException("Idle 尾巴测试没有输出 Pose");
            var sleepPose = update.Invoke(
                sleepEngine,
                [1.0 / 60.0, CreateInput("Resting", autonomousState: "Sleep")])
                ?? throw new InvalidOperationException("Sleep 尾巴测试没有输出 Pose");

            if (ReadString(sleepPose, "MotionState") != "Sleep")
            {
                continue;
            }

            sawSleep = true;
            if (frame < 300)
            {
                // 先让 Sleep 路由完成并给尾巴 spring 足够时间消散清醒状态的残余动量。
                continue;
            }

            var idleTail = RequireProperty(idlePose.GetType(), "TailBase").GetValue(idlePose)
                ?? throw new InvalidOperationException("Idle TailBase 为空");
            var sleepTail = RequireProperty(sleepPose.GetType(), "TailBase").GetValue(sleepPose)
                ?? throw new InvalidOperationException("Sleep TailBase 为空");
            var idleRotation  = ReadDouble(idleTail, "RotationDeg");
            var sleepRotation = ReadDouble(sleepTail, "RotationDeg");
            idleEnergy  += idleRotation * idleRotation;
            sleepEnergy += sleepRotation * sleepRotation;
            samples++;
        }

        Assert(sawSleep, "睡眠尾巴测试未进入 Sleep");
        Assert(samples >= 240, "睡眠尾巴测试缺少足够的稳定态采样窗口");

        var idleRms  = Math.Sqrt(idleEnergy / samples);
        var sleepRms = Math.Sqrt(sleepEnergy / samples);
        Assert(sleepRms > 0.05,
            "睡眠尾巴不能完全冻结；应保留非常轻微的生命感微动");
        Assert(sleepRms < idleRms * 0.45,
            $"Sleep 尾巴 RMS 必须显著低于清醒 Idle；idle={idleRms:F3}, sleep={sleepRms:F3}");
    }

    private static object CreateInput(
        string baseState,
        double pointerX = 0.0,
        double pointerY = 0.0,
        bool pointerInside = false,
        string? autonomousState = null)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        var input = Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
            pointerX,
            pointerY,
            pointerInside,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            72.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException($"无法创建 {baseState} MotionInput");

        if (autonomousState is not null)
        {
            var motionStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
            RequireProperty(inputType, "AutonomousState").SetValue(
                input,
                Enum.Parse(motionStateType, autonomousState));
        }

        return input;
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
