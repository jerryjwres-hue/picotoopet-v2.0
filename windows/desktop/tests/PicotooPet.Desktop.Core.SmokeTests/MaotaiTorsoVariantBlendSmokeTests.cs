using System.Globalization;
using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结独立 torso surface 的连续混合合同，禁止回退到姿态状态帧硬切。</summary>
internal static class MaotaiTorsoVariantBlendSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyContinuousBlendMath();
        VerifyRasterSurfaceWiring();
    }

    private static void VerifyContinuousBlendMath()
    {
        var blendType = RequireType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiTorsoVariantBlend");
        var fromScaleY = blendType.GetMethod(
            "FromScaleY",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiTorsoVariantBlend 缺少 FromScaleY");

        var neutral = InvokeBlend(fromScaleY, 1.0);
        AssertNear(ReadDouble(neutral, "Neutral"), 1.0, 0.000001,
            "中性 bodyScaleY 必须 100% 使用 torso_neutral");
        AssertNear(ReadDouble(neutral, "Crouch"), 0.0, 0.000001,
            "中性 bodyScaleY 不得泄漏 crouch surface");
        AssertNear(ReadDouble(neutral, "Stretch"), 0.0, 0.000001,
            "中性 bodyScaleY 不得泄漏 stretch surface");

        var crouch = InvokeBlend(fromScaleY, 0.915);
        Assert(ReadDouble(crouch, "Crouch") >= 0.95,
            "JumpPrep 深压缩必须主要使用独立 torso_crouch surface");
        Assert(ReadDouble(crouch, "Stretch") <= 0.000001,
            "压缩姿态不得同时显示 stretch surface");
        AssertWeightsNormalized(crouch, "crouch");

        var stretch = InvokeBlend(fromScaleY, 1.070);
        Assert(ReadDouble(stretch, "Stretch") >= 0.95,
            "Yawn 峰值伸展必须主要使用独立 torso_stretch surface");
        Assert(ReadDouble(stretch, "Crouch") <= 0.000001,
            "伸展姿态不得同时显示 crouch surface");
        AssertWeightsNormalized(stretch, "stretch");

        var justCrouched  = InvokeBlend(fromScaleY, 0.999);
        var justStretched = InvokeBlend(fromScaleY, 1.001);
        Assert(ReadDouble(justCrouched, "Neutral") > 0.97,
            "neutral -> crouch 必须连续渐变，禁止 1px/1 帧硬切");
        Assert(ReadDouble(justStretched, "Neutral") > 0.97,
            "neutral -> stretch 必须连续渐变，禁止 1px/1 帧硬切");
        AssertWeightsNormalized(justCrouched, "near-neutral crouch");
        AssertWeightsNormalized(justStretched, "near-neutral stretch");

        var invalid = InvokeBlend(fromScaleY, double.NaN);
        AssertNear(ReadDouble(invalid, "Neutral"), 1.0, 0.000001,
            "NaN bodyScaleY 必须 fail-safe 回到 neutral surface");
        AssertWeightsNormalized(invalid, "NaN fallback");
    }

    private static void VerifyRasterSurfaceWiring()
    {
        var root     = FindRepositoryRoot();
        var xaml     = File.ReadAllText(Path.Combine(
            root, "windows", "desktop", "src", "PicotooPet.Desktop",
            "Views", "Controls", "AssistantPetPanel.xaml"));
        var panel    = File.ReadAllText(Path.Combine(
            root, "windows", "desktop", "src", "PicotooPet.Desktop",
            "Views", "Controls", "AssistantPetPanel.Maotai.cs"));
        var renderer = File.ReadAllText(Path.Combine(
            root, "windows", "desktop", "src", "PicotooPet.Desktop",
            "Views", "Controls", "MaotaiMotion", "MaotaiRasterRenderer.cs"));

        Assert(xaml.Contains("x:Name=\"MaotaiV2TorsoNeutral\"", StringComparison.Ordinal),
            "v2 XAML 缺少 torso_neutral 独立 surface");
        Assert(xaml.Contains("x:Name=\"MaotaiV2TorsoCrouch\"", StringComparison.Ordinal),
            "v2 XAML 缺少 torso_crouch 独立 surface");
        Assert(xaml.Contains("x:Name=\"MaotaiV2TorsoStretch\"", StringComparison.Ordinal),
            "v2 XAML 缺少 torso_stretch 独立 surface");
        Assert(panel.Contains("MaotaiAssetManifest.TorsoCrouch", StringComparison.Ordinal) &&
               panel.Contains("MaotaiAssetManifest.TorsoStretch", StringComparison.Ordinal),
            "loader/required-rig 必须真正消费 crouch/stretch 资产");
        Assert(renderer.Contains("MaotaiTorsoVariantBlend.FromScaleY", StringComparison.Ordinal),
            "RasterRenderer 必须由连续 bodyScaleY 驱动 torso surface blend");
        Assert(renderer.Contains("TorsoNeutral.Opacity", StringComparison.Ordinal) &&
               renderer.Contains("TorsoCrouch.Opacity", StringComparison.Ordinal) &&
               renderer.Contains("TorsoStretch.Opacity", StringComparison.Ordinal),
            "renderer 必须连续写入三张独立 torso surface 的 opacity");
    }

    private static object InvokeBlend(MethodInfo method, double scaleY) =>
        method.Invoke(null, [scaleY])
        ?? throw new InvalidOperationException("Torso variant blend 没有返回值");

    private static void AssertWeightsNormalized(object blend, string label)
    {
        var neutral = ReadDouble(blend, "Neutral");
        var crouch  = ReadDouble(blend, "Crouch");
        var stretch = ReadDouble(blend, "Stretch");
        Assert(neutral >= 0.0 && neutral <= 1.0, $"{label} neutral 权重越界");
        Assert(crouch >= 0.0 && crouch <= 1.0, $"{label} crouch 权重越界");
        Assert(stretch >= 0.0 && stretch <= 1.0, $"{label} stretch 权重越界");
        AssertNear(neutral + crouch + stretch, 1.0, 0.000001,
            $"{label} torso 权重总和必须恒等于 1");
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName, throwOnError: false)
        ?? throw new InvalidOperationException($"缺少类型 {fullName}");

    private static double ReadDouble(object value, string propertyName)
    {
        var property = value.GetType().GetProperty(
            propertyName,
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
            ?? throw new InvalidOperationException($"缺少属性 {propertyName}");
        return Convert.ToDouble(
            property.GetValue(value),
            CultureInfo.InvariantCulture);
    }

    private static string FindRepositoryRoot()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            if (Directory.Exists(Path.Combine(current.FullName, "windows")) &&
                Directory.Exists(Path.Combine(current.FullName, "tests")))
            {
                return current.FullName;
            }
            current = current.Parent;
        }

        throw new InvalidOperationException("无法定位仓库根目录");
    }

    private static void AssertNear(double actual, double expected, double tolerance, string message)
    {
        Assert(double.IsFinite(actual) && Math.Abs(actual - expected) <= tolerance, message);
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}