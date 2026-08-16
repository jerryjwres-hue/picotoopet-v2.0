using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结光栅骨骼坐标约定：IK 角度以 +X 为零轴，而腿部 PNG 的自然零轴是向下。
/// 如果缺少这层转换，正确的 IK 数值也会把腿整体旋转约 90 度。
/// </summary>
internal static class MaotaiRasterAxisV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var axisType = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterAxis")
            ?? throw new InvalidOperationException("缺少 MaotaiRasterAxis 光栅零轴转换");
        var method = axisType.GetMethod(
            "LegRotationFromIkDegrees",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiRasterAxis 缺少 LegRotationFromIkDegrees");

        AssertNear(0.0, Invoke(method, 90.0),
            "IK 向下 90° 必须对应竖直腿 PNG 的 0°");
        AssertNear(-90.0, Invoke(method, 0.0),
            "IK 向右 0° 必须把竖直腿 PNG 转为 -90°");
        AssertNear(90.0, Invoke(method, 180.0),
            "IK 向左 180° 必须把竖直腿 PNG 转为 90°");
        AssertNear(43.0, Invoke(method, 133.0),
            "典型前腿 IK 133° 应落到约 43° 的可视角，而不是侧飞 133°");
    }

    private static double Invoke(MethodInfo method, double value)
    {
        var result = method.Invoke(null, [value]);
        return result is double angle
            ? angle
            : throw new InvalidOperationException("LegRotationFromIkDegrees 必须返回 double");
    }

    private static void AssertNear(double expected, double actual, string message)
    {
        if (!double.IsFinite(actual) || Math.Abs(expected - actual) > 0.000001)
        {
            throw new InvalidOperationException(
                $"{message}；expected={expected:F3}, actual={actual:F3}");
        }
    }
}
