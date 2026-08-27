using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结 v2 眼部层级：独立瞳孔只能在 open-eye 权重可见时显示，
/// 半闭与闭眼阶段必须同步淡出，避免出现悬浮瞳孔。
/// </summary>
internal static class MaotaiPupilVisibilityV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var type = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiEyeLayerOpacity")
            ?? throw new InvalidOperationException("缺少 MaotaiEyeLayerOpacity 眼部层级权重");
        var method = type.GetMethod(
            "PupilFromOpenWeight",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiEyeLayerOpacity 缺少 PupilFromOpenWeight");

        AssertNear(1.0, Invoke(method, 1.0), "睁眼时瞳孔必须完全可见");
        AssertNear(0.35, Invoke(method, 0.35), "眨眼交叉淡化时瞳孔必须跟随 open-eye 权重");
        AssertNear(0.0, Invoke(method, 0.0), "半闭/闭眼时瞳孔必须完全隐藏");
    }

    private static double Invoke(MethodInfo method, double value) =>
        (double)(method.Invoke(null, [value])
            ?? throw new InvalidOperationException("PupilFromOpenWeight 返回 null"));

    private static void AssertNear(double expected, double actual, string message)
    {
        if (!double.IsFinite(actual) || Math.Abs(expected - actual) > 0.000001)
        {
            throw new InvalidOperationException(
                $"{message}；expected={expected:F3}, actual={actual:F3}");
        }
    }
}
