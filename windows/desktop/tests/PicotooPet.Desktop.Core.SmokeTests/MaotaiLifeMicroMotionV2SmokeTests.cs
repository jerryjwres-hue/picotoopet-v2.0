using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结待机生命感：自然眨眼必须来自 Motion Engine，不能靠整图状态帧。</summary>
internal static class MaotaiLifeMicroMotionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyIdleBlinking();
        VerifyOfflineEyesStayClosed();
    }

    private static void VerifyIdleBlinking()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 101, 72.0)
            ?? throw new InvalidOperationException("无法创建待机生命感 Motion Engine");

        var sawHalf   = false;
        var sawClosed = false;
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

    private static object CreateInput(string baseState)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
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

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
