using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 TailBase -> TailMid -> TailTip 的局部连接层级，禁止三段重新退化为 Body 下并列坐标。</summary>
internal static class MaotaiTailHierarchyV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var rendererType = RequireType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer");
        var poseType = RequireType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBonePose");
        var resolve = rendererType.GetMethod(
            "ResolveTailChildWorldPose",
            BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException(
                "MaotaiRasterRenderer 缺少尾巴局部层级解析器");
        var resolveVisual = rendererType.GetMethod(
            "ResolveTailVisualChildWorldPose",
            BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException(
                "MaotaiRasterRenderer 缺少尾巴视觉重叠解析器");

        var basePose = CreatePose(poseType, -20.0, -10.0, 0.0);
        var midLocal = CreatePose(poseType, -11.0, -8.0, 12.0);
        var midWorld = resolve.Invoke(null, [basePose, midLocal])
            ?? throw new InvalidOperationException("TailMid 层级解析没有返回 Pose");

        AssertNear(ReadDouble(midWorld, "X"), -31.0,
            "TailMid X 必须累积 Base 局部偏移");
        AssertNear(ReadDouble(midWorld, "Y"), -18.0,
            "TailMid Y 必须累积 Base 局部偏移");
        AssertNear(ReadDouble(midWorld, "RotationDeg"), 12.0,
            "TailMid spring heading 已是段级 world heading，禁止重复叠加 Base 角度");

        var rotatedBase = CreatePose(poseType, -20.0, -10.0, 90.0);
        var rotatedMid = resolve.Invoke(null, [rotatedBase, midLocal])
            ?? throw new InvalidOperationException("旋转 TailMid 层级解析没有返回 Pose");

        AssertNear(ReadDouble(rotatedMid, "X"), -12.0,
            "父段 90 度时 TailMid 局部 Y 必须参与旋转后的 X");
        AssertNear(ReadDouble(rotatedMid, "Y"), -21.0,
            "父段 90 度时 TailMid 局部 X 必须参与旋转后的 Y");
        AssertNear(ReadDouble(rotatedMid, "RotationDeg"), 12.0,
            "父段旋转不得二次叠加到 TailMid world heading");

        // Visual overlap      : renderer may tuck the displayed child into its parent, but must preserve
        //                       the child's spring heading and leave the canonical hierarchy math untouched.
        var visualMid = resolveVisual.Invoke(null, [basePose, midLocal, 0.60])
            ?? throw new InvalidOperationException("TailMid 视觉重叠解析没有返回 Pose");
        AssertNear(ReadDouble(visualMid, "X"), -26.6,
            "TailMid 视觉 X 应把局部连接距离压缩到 60%");
        AssertNear(ReadDouble(visualMid, "Y"), -14.8,
            "TailMid 视觉 Y 应把局部连接距离压缩到 60%");
        AssertNear(ReadDouble(visualMid, "RotationDeg"), 12.0,
            "TailMid 视觉重叠不得修改 spring heading");

        var visualRotatedMid = resolveVisual.Invoke(null, [rotatedBase, midLocal, 0.60])
            ?? throw new InvalidOperationException("旋转 TailMid 视觉重叠解析没有返回 Pose");
        AssertNear(ReadDouble(visualRotatedMid, "X"), -15.2,
            "父段 90 度时 TailMid 视觉连接仍需按父段旋转");
        AssertNear(ReadDouble(visualRotatedMid, "Y"), -16.6,
            "父段 90 度时 TailMid 视觉连接距离应保持 60%");

        var tipLocal = CreatePose(poseType, -10.0, -7.0, 18.0);
        var tipWorld = resolve.Invoke(null, [midWorld, tipLocal])
            ?? throw new InvalidOperationException("TailTip 层级解析没有返回 Pose");

        var radians   = 12.0 * Math.PI / 180.0;
        var expectedX = -31.0 + (-10.0 * Math.Cos(radians)) - (-7.0 * Math.Sin(radians));
        var expectedY = -18.0 + (-10.0 * Math.Sin(radians)) + (-7.0 * Math.Cos(radians));
        AssertNear(ReadDouble(tipWorld, "X"), expectedX,
            "TailTip 必须从已经解析后的 TailMid 继续累积局部偏移");
        AssertNear(ReadDouble(tipWorld, "Y"), expectedY,
            "TailTip 必须从已经解析后的 TailMid 继续累积局部偏移");
    }

    private static object CreatePose(
        Type poseType,
        double x,
        double y,
        double rotationDeg) =>
        Activator.CreateInstance(poseType, x, y, rotationDeg, 1.0, 1.0)
        ?? throw new InvalidOperationException("无法创建 MaotaiBonePose");

    private static double ReadDouble(object value, string propertyName) =>
        Convert.ToDouble(
            value.GetType().GetProperty(propertyName)?.GetValue(value)
            ?? throw new InvalidOperationException($"缺少 {propertyName}"),
            System.Globalization.CultureInfo.InvariantCulture);

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName)
        ?? throw new InvalidOperationException($"缺少类型 {fullName}");

    private static void AssertNear(double actual, double expected, string contract)
    {
        if (!double.IsFinite(actual) || Math.Abs(actual - expected) > 0.000001)
        {
            throw new InvalidOperationException(
                $"{contract}；expected={expected:F6}, actual={actual:F6}");
        }
    }
}
