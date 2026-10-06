using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结“会自己睡觉”这一真实产品入口，避免 Sleep 只存在于动画图而永远不会被自主行为请求。</summary>
internal static class MaotaiAutonomousSleepV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var controllerType = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAutonomousBehaviorController",
            throwOnError: true)!;
        var update = controllerType.GetMethod(
            "Update",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            binder: null,
            types: [typeof(double), typeof(double), typeof(double), typeof(double), typeof(bool), typeof(bool)],
            modifiers: null)
            ?? throw new InvalidOperationException(
                "MaotaiAutonomousBehaviorController 缺少确定性的 Update(dt,currentX,minX,maxX,floating,enabled)");
        var controller = Activator.CreateInstance(controllerType, 73)
            ?? throw new InvalidOperationException("无法创建自主行为 controller");

        var currentX = 72.0;
        var sawSleep = false;
        for (var frame = 0; frame < 7200; frame++)
        {
            var intent = update.Invoke(controller, [0.05, currentX, 18.0, 150.0, true, true])
                ?? throw new InvalidOperationException("自主行为 controller 没有返回 intent");
            currentX = ReadDouble(intent, "TargetX");

            if (string.Equals(
                    ReadOptionalEnumName(intent, "AutonomousState"),
                    "Sleep",
                    StringComparison.Ordinal))
            {
                sawSleep = true;
                break;
            }
        }

        Assert(sawSleep,
            "悬浮 Resting 长时间运行从未产生自主 Sleep；当前只能趴下，无法形成真正的小睡行为");
    }

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static double ReadDouble(object target, string name) =>
        Convert.ToDouble(ReadProperty(target, name), System.Globalization.CultureInfo.InvariantCulture);

    private static string? ReadOptionalEnumName(object target, string name)
    {
        var property = target.GetType().GetProperty(
            name,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");
        return property.GetValue(target)?.ToString();
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
