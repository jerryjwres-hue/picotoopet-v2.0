using System.Collections.Concurrent;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Views.Controls.MaotaiMotion;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>只读取固定应用 UI 目录中的茅台素材；任何解码失败都必须局部降级。</summary>
internal static class MaotaiPetAssetLoader
{
    private static readonly ConcurrentDictionary<string, ImageSource> Cache =
        new(StringComparer.OrdinalIgnoreCase);

    // v1 root          : retained only while the Draft branch still compiles the compatibility renderer.
    private static readonly string AssetRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "ui-assets",
        "maotai",
        "v1");

    // v2 root          : fixed app-owned directory; no arbitrary user-file enumeration is ever performed.
    private static readonly string V2AssetRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "ui-assets",
        "maotai",
        "v2");

    private static readonly ImageSource TransparentFallback = CreateTransparentFallback();

    /// <summary>v1 兼容入口；本地整图不存在/损坏时安全回退到程序集资源。</summary>
    public static ImageSource LoadOrFallback(
        string fileName,
        Uri fallbackUri)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        ArgumentNullException.ThrowIfNull(fallbackUri);

        var cacheKey = $"v1|{fileName}|{fallbackUri}";
        return Cache.GetOrAdd(
            cacheKey,
            _ => TryLoadLocal(AssetRoot, fileName) ??
                TryLoadPackResource(fallbackUri) ??
                TransparentFallback);
    }

    /// <summary>加载 v2 真正独立的透明部件；不在白名单或损坏时返回透明安全图。</summary>
    public static ImageSource LoadV2Part(string fileName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        if (!MaotaiAssetManifest.IsKnownAsset(fileName))
        {
            return TransparentFallback;
        }

        var cacheKey = $"v2|{fileName}";
        return Cache.GetOrAdd(
            cacheKey,
            _ => TryLoadLocal(V2AssetRoot, fileName) ?? TransparentFallback);
    }

    /// <summary>只检查固定白名单文件是否可成功解码，用于启用 v2 可见 Rig 前的完整性门槛。</summary>
    public static bool HasUsableV2Part(string fileName)
    {
        if (!MaotaiAssetManifest.IsKnownAsset(fileName))
        {
            return false;
        }

        return TryLoadLocal(V2AssetRoot, fileName) is not null;
    }

    private static BitmapImage? TryLoadLocal(
        string root,
        string fileName)
    {
        var fullPath = Path.Combine(root, fileName);
        try
        {
            if (!File.Exists(fullPath))
            {
                return null;
            }

            using var stream = File.Open(
                fullPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read);
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption  = BitmapCacheOption.OnLoad;
            bitmap.StreamSource = stream;
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch (Exception exception) when (
            exception is IOException
            or UnauthorizedAccessException
            or NotSupportedException
            or ArgumentException
            or FileFormatException)
        {
            // Asset failure    : decorative art can disappear, but it must never take down Shell/Core/Worker/task flows.
            return null;
        }
    }

    private static BitmapImage? TryLoadPackResource(Uri fallbackUri)
    {
        try
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.UriSource   = fallbackUri;
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch (Exception exception) when (
            exception is IOException
            or UnauthorizedAccessException
            or NotSupportedException
            or ArgumentException
            or FileFormatException)
        {
            // Pack failure     : historical placeholder resources may be malformed; degrade instead of crashing Shell.
            return null;
        }
    }

    private static DrawingImage CreateTransparentFallback()
    {
        var drawing = new GeometryDrawing(
            System.Windows.Media.Brushes.Transparent,
            null,
            Geometry.Empty);
        drawing.Freeze();

        var image = new DrawingImage(drawing);
        image.Freeze();
        return image;
    }

    private static bool IsKnownAsset(string fileName) => fileName is
        "working.png"
        or "working_tired.png"
        or "working_annoyed.png"
        or "resting.png"
        or "offline.png";
}
