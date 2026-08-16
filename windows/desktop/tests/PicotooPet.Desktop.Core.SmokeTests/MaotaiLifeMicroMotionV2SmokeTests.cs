using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结待机生命感：眨眼与视线必须来自 Motion Engine，不能靠整图状态帧。</summary>
internal static class MaotaiLifeMicroMotionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyIdleBlinking();
        VerifyOfflineEyesStayClosed();
        VerifyIdleGazeWanders();
        VerifyPointerOverridesAutonomousGaze();
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

    private static object CreateInput(
        string baseState,
        double pointerX = 0.0,
        double pointerY = 0.0,
        bool pointerInside = false)
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
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            72.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException($"无法创建 {baseState} MotionInput");
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
