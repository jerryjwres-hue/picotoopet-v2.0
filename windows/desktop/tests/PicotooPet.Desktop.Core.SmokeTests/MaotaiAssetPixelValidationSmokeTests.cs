using System.Reflection;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>解码正式 v2 PNG，冻结透明边缘、像素密度和可见内容边界合同。</summary>
internal static class MaotaiAssetPixelValidationSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var root      = FindRepositoryRoot();
        var assetRoot = Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Assets",
            "Maotai",
            "V2");
        var manifestType = DesktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest")
            ?? throw new InvalidOperationException("缺少 MaotaiAssetManifest");
        var tryGet = manifestType.GetMethod(
            "TryGetDescriptor",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiAssetManifest 缺少 TryGetDescriptor");

        string[] requiredAssets =
        [
            "torso_neutral.png", "torso_crouch.png", "torso_stretch.png", "chest_fur.png",
            "head.png", "muzzle.png", "ear_left.png", "ear_right.png",
            "eye_left_open.png", "eye_right_open.png", "eye_left_half.png", "eye_right_half.png",
            "eye_left_closed.png", "eye_right_closed.png", "pupil_left.png", "pupil_right.png",
            "brow_left.png", "brow_right.png",
            "mouth_smile.png", "mouth_tired.png", "mouth_annoyed.png", "mouth_yawn.png", "mouth_tongue.png",
            "front_left_upper.png", "front_left_lower.png", "front_left_paw.png",
            "front_right_upper.png", "front_right_lower.png", "front_right_paw.png",
            "hind_left_upper.png", "hind_left_lower.png", "hind_left_paw.png",
            "hind_right_upper.png", "hind_right_lower.png", "hind_right_paw.png",
            "tail_base.png", "tail_mid.png", "tail_tip.png",
            "headphone_band.png", "headphone_left.png", "headphone_right.png",
            "laptop.png", "drink.png", "shadow.png",
        ];

        foreach (var fileName in requiredAssets)
        {
            var path = Path.Combine(assetRoot, fileName);
            Assert(File.Exists(path), $"v2 正式独立透明资产尚未交付：{fileName}");

            object?[] arguments = [fileName, null];
            Assert((bool)tryGet.Invoke(null, arguments)!, $"v2 manifest 缺少 {fileName}");
            var descriptor = arguments[1]
                ?? throw new InvalidOperationException($"v2 descriptor 为空：{fileName}");
            var logicalWidth  = ReadDouble(descriptor, "Width");
            var logicalHeight = ReadDouble(descriptor, "Height");

            ValidatePixels(path, fileName, logicalWidth, logicalHeight);
        }
    }

    private static void ValidatePixels(
        string path,
        string fileName,
        double logicalWidth,
        double logicalHeight)
    {
        using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        var decoder = new PngBitmapDecoder(
            stream,
            BitmapCreateOptions.PreservePixelFormat,
            BitmapCacheOption.OnLoad);
        Assert(decoder.Frames.Count == 1, $"v2 PNG 必须是单帧：{fileName}");

        var frame = decoder.Frames[0];
        Assert(frame.PixelWidth >= Math.Ceiling(logicalWidth * 2.0),
            $"v2 PNG 横向像素密度不足 2x logical：{fileName}");
        Assert(frame.PixelHeight >= Math.Ceiling(logicalHeight * 2.0),
            $"v2 PNG 纵向像素密度不足 2x logical：{fileName}");

        var converted = new FormatConvertedBitmap(frame, PixelFormats.Bgra32, null, 0.0);
        var stride    = converted.PixelWidth * 4;
        var pixels    = new byte[stride * converted.PixelHeight];
        converted.CopyPixels(pixels, stride, 0);

        var visibleCount     = 0L;
        var transparentCount = 0L;
        var minX             = converted.PixelWidth;
        var minY             = converted.PixelHeight;
        var maxX             = -1;
        var maxY             = -1;

        for (var y = 0; y < converted.PixelHeight; y++)
        {
            for (var x = 0; x < converted.PixelWidth; x++)
            {
                var alpha = pixels[(y * stride) + (x * 4) + 3];
                if (alpha == 0)
                {
                    transparentCount++;
                    continue;
                }

                visibleCount++;
                minX = Math.Min(minX, x);
                minY = Math.Min(minY, y);
                maxX = Math.Max(maxX, x);
                maxY = Math.Max(maxY, y);
            }
        }

        Assert(visibleCount > 0, $"v2 PNG 没有任何可见像素：{fileName}");
        Assert(transparentCount > 0, $"v2 PNG alpha 全不透明，疑似扁平背景：{fileName}");
        Assert(minX >= 2 && minY >= 2 &&
               maxX <= converted.PixelWidth - 3 &&
               maxY <= converted.PixelHeight - 3,
            $"v2 PNG 可见毛发贴到画布边缘，旋转/缩放可能被裁断：{fileName}");

        if (fileName is "torso_neutral.png" or "torso_crouch.png" or "torso_stretch.png")
        {
            var visibleWidthRatio  = (maxX - minX + 1.0) / converted.PixelWidth;
            var visibleHeightRatio = (maxY - minY + 1.0) / converted.PixelHeight;
            Assert(visibleWidthRatio >= 0.78,
                $"v2 torso 有效横向 silhouette 过窄，会被 head 覆盖：{fileName} ratio={visibleWidthRatio:F3}");
            Assert(visibleHeightRatio >= 0.80,
                $"v2 torso 有效纵向 silhouette 过小，肢体根部无法藏入毛发：{fileName} ratio={visibleHeightRatio:F3}");
        }

        AssertOuterBorderTransparent(pixels, converted.PixelWidth, converted.PixelHeight, stride, fileName);
    }

    private static void AssertOuterBorderTransparent(
        byte[] pixels,
        int width,
        int height,
        int stride,
        string fileName)
    {
        for (var x = 0; x < width; x++)
        {
            Assert(ReadAlpha(pixels, stride, x, 0) == 0,
                $"v2 PNG 顶边 alpha 非零：{fileName}");
            Assert(ReadAlpha(pixels, stride, x, height - 1) == 0,
                $"v2 PNG 底边 alpha 非零：{fileName}");
        }

        for (var y = 0; y < height; y++)
        {
            Assert(ReadAlpha(pixels, stride, 0, y) == 0,
                $"v2 PNG 左边 alpha 非零：{fileName}");
            Assert(ReadAlpha(pixels, stride, width - 1, y) == 0,
                $"v2 PNG 右边 alpha 非零：{fileName}");
        }
    }

    private static byte ReadAlpha(byte[] pixels, int stride, int x, int y) =>
        pixels[(y * stride) + (x * 4) + 3];

    private static double ReadDouble(object value, string propertyName)
    {
        var property = value.GetType().GetProperty(propertyName, BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException($"{value.GetType().Name} 缺少 {propertyName}");
        return (double)(property.GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));
    }

    private static string FindRepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory);
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        for (var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        throw new DirectoryNotFoundException("无法定位 PicotooPet 仓库根目录。");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
