using System.Reflection;
using System.Threading;
using System.Windows;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 Manifest Pivot 作为独立 Raster Skeleton 运行时旋转中心的单一真源。</summary>
internal static class MaotaiManifestPivotBindingV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;
    private static readonly Type PanelType = typeof(AssistantPetPanel);

    public static void Run() => RunOnSta(() =>
    {
        var panel = new AssistantPetPanel();
        var buildVisuals = PanelType.GetMethod(
            "BuildMaotaiRasterVisuals",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("AssistantPetPanel 缺少 BuildMaotaiRasterVisuals");
        var visuals = buildVisuals.Invoke(panel, null)
            ?? throw new InvalidOperationException("BuildMaotaiRasterVisuals 没有返回运行时可见层");

        (string VisualProperty, string AssetFile)[] directParts =
        [
            ("Chest", "chest_fur.png"),
            ("LeftEar", "ear_left.png"),
            ("RightEar", "ear_right.png"),
            ("LeftPupil", "pupil_left.png"),
            ("RightPupil", "pupil_right.png"),
            ("FrontLeftUpper", "front_left_upper.png"),
            ("FrontLeftLower", "front_left_lower.png"),
            ("FrontLeftPaw", "front_left_paw.png"),
            ("FrontRightUpper", "front_right_upper.png"),
            ("FrontRightLower", "front_right_lower.png"),
            ("FrontRightPaw", "front_right_paw.png"),
            ("HindLeftUpper", "hind_left_upper.png"),
            ("HindLeftLower", "hind_left_lower.png"),
            ("HindLeftPaw", "hind_left_paw.png"),
            ("HindRightUpper", "hind_right_upper.png"),
            ("HindRightLower", "hind_right_lower.png"),
            ("HindRightPaw", "hind_right_paw.png"),
            ("TailBase", "tail_base.png"),
            ("TailMid", "tail_mid.png"),
            ("TailTip", "tail_tip.png"),
        ];

        var failures = new List<string>();
        foreach (var (visualProperty, assetFile) in directParts)
        {
            var part = ReadProperty(visuals, visualProperty);
            var element = ReadProperty(part, "Element") as FrameworkElement
                ?? throw new InvalidOperationException($"{visualProperty}.Element 不是 FrameworkElement");
            var expected = ReadNormalizedManifestPivot(assetFile);
            var actual = element.RenderTransformOrigin;

            if (Math.Abs(actual.X - expected.X) > 0.0005 ||
                Math.Abs(actual.Y - expected.Y) > 0.0005)
            {
                failures.Add(
                    $"{assetFile}: runtime=({actual.X:F3},{actual.Y:F3}) manifest=({expected.X:F3},{expected.Y:F3})");
            }
        }

        Assert(failures.Count == 0,
            "独立骨骼运行时 Pivot 没有使用 Manifest 单一真源，正式资产会绕错误旋转中心运动:\n - " +
            string.Join("\n - ", failures));
    });

    private static Point ReadNormalizedManifestPivot(string assetFile)
    {
        var manifestType = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest",
            throwOnError: true)!;
        var tryGet = manifestType.GetMethod(
            "TryGetDescriptor",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiAssetManifest 缺少 TryGetDescriptor");
        object?[] arguments = [assetFile, null];
        Assert((bool)tryGet.Invoke(null, arguments)!, $"Manifest 缺少 {assetFile}");
        var descriptor = arguments[1]
            ?? throw new InvalidOperationException($"Manifest descriptor 为空: {assetFile}");
        var width = ReadDouble(descriptor, "Width");
        var height = ReadDouble(descriptor, "Height");
        var pivotX = ReadDouble(descriptor, "PivotX");
        var pivotY = ReadDouble(descriptor, "PivotY");
        Assert(width > 0.0 && height > 0.0, $"Manifest 尺寸非法: {assetFile}");
        return new Point(pivotX / width, pivotY / height);
    }

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(
            name,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static double ReadDouble(object target, string name) =>
        Convert.ToDouble(
            ReadProperty(target, name),
            System.Globalization.CultureInfo.InvariantCulture);

    private static void RunOnSta(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (failure is not null)
        {
            throw new InvalidOperationException(
                "Maotai Manifest Pivot binding STA smoke failed.",
                failure);
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
