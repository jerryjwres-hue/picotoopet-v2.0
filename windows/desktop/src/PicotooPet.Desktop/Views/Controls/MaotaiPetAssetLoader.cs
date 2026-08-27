using System.Collections.Concurrent;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Views.Controls.MaotaiMotion;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>只读取固定应用 UI 目录或安装包内置目录中的茅台素材；任何解码失败都必须局部降级。</summary>
internal static class MaotaiPetAssetLoader
{
    private static readonly ConcurrentDictionary<string, ImageSource> Cache =
        new(StringComparer.OrdinalIgnoreCase);

    // v1 root              : retained only while the Draft branch still compiles the compatibility renderer.
    private static readonly string AssetRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "ui-assets",
        "maotai",
        "v1");

    // v2 override root      : fixed app-owned directory; never enumerate arbitrary user folders.
    private static readonly string V2AssetRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "ui-assets",
        "maotai",
        "v2");

    // v2 packaged root      : release payload carries the same whitelist so a fresh install needs no manual art copy.
    private static readonly string PackagedV2AssetRoot = Path.Combine(
        AppContext.BaseDirectory,
        "ui-assets",
        "maotai",
        "v2");

    private static readonly ImageSource TransparentFallback = CreateTransparentFallback();

    /// <summary>v1 兼容入口；只接受历史五个固定文件名。</summary>
    public static ImageSource LoadOrFallback(
        string fileName,
        Uri fallbackUri)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        ArgumentNullException.ThrowIfNull(fallbackUri);

        if (!IsKnownV1Asset(fileName))
        {
            return TransparentFallback;
        }

        var cacheKey = $"v1|{fileName}|{fallbackUri}";
        return Cache.GetOrAdd(
            cacheKey,
            _ => TryLoadLocal(AssetRoot, fileName) ??
                TryLoadPackResource(fallbackUri) ??
                TransparentFallback);
    }

    /// <summary>加载 v2 真正独立的透明部件；优先固定本地覆盖，其次 installer 内置资产，最后透明降级。</summary>
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
            _ => TryLoadLocal(V2AssetRoot, fileName) ??
                TryLoadLocal(PackagedV2AssetRoot, fileName) ??
                TransparentFallback);
    }

    /// <summary>复用 v2 缓存判断部件是否可用；初始化完整性检查不会重复解码同一 PNG。</summary>
    public static bool HasUsableV2Part(string fileName)
    {
        if (!MaotaiAssetManifest.IsKnownAsset(fileName))
        {
            return false;
        }

        return !ReferenceEquals(
            LoadV2Part(fileName),
            TransparentFallback);
    }

    private static BitmapImage? TryLoadLocal(
        string root,
        string fileName)
    {
        if (!MaotaiAssetManifest.IsKnownAsset(fileName) &&
            !IsKnownV1Asset(fileName))
        {
            return null;
        }

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

            if (bitmap.PixelWidth <= 0 || bitmap.PixelHeight <= 0)
            {
                return null;
            }

            if (MaotaiAssetManifest.TryGetDescriptor(fileName, out var descriptor) &&
                !ValidateV2Bitmap(bitmap, descriptor))
            {
                return null;
            }

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
            // Asset failure        : decorative art may disappear, but Shell/Core/Worker/task flows stay alive.
            return null;
        }
    }

    /// <summary>v2 资产只在初始化时做一次像素合同检查；每帧渲染绝不访问文件或解码图片。</summary>
    private static bool ValidateV2Bitmap(
        BitmapSource bitmap,
        in MaotaiAssetDescriptor descriptor)
    {
        var minimumWidth  = (int)Math.Ceiling(descriptor.Width * 2.0);
        var minimumHeight = (int)Math.Ceiling(descriptor.Height * 2.0);
        if (bitmap.PixelWidth < minimumWidth || bitmap.PixelHeight < minimumHeight)
        {
            return false;
        }

        // Canonical export        : require explicit 8-bit alpha so an opaque RGB sheet cannot masquerade as a rig part.
        if (bitmap.Format != PixelFormats.Bgra32 &&
            bitmap.Format != PixelFormats.Pbgra32)
        {
            return false;
        }

        var converted = bitmap.Format == PixelFormats.Bgra32
            ? bitmap
            : new FormatConvertedBitmap(bitmap, PixelFormats.Bgra32, null, 0.0);
        var row = new byte[converted.PixelWidth * 4];
        var column = new byte[converted.PixelHeight * 4];

        converted.CopyPixels(
            new Int32Rect(0, 0, converted.PixelWidth, 1),
            row,
            row.Length,
            0);
        if (!AllAlphaZero(row))
        {
            return false;
        }

        converted.CopyPixels(
            new Int32Rect(0, converted.PixelHeight - 1, converted.PixelWidth, 1),
            row,
            row.Length,
            0);
        if (!AllAlphaZero(row))
        {
            return false;
        }

        converted.CopyPixels(
            new Int32Rect(0, 0, 1, converted.PixelHeight),
            column,
            4,
            0);
        if (!AllAlphaZero(column))
        {
            return false;
        }

        converted.CopyPixels(
            new Int32Rect(converted.PixelWidth - 1, 0, 1, converted.PixelHeight),
            column,
            4,
            0);
        return AllAlphaZero(column);
    }

    private static bool AllAlphaZero(byte[] pixels)
    {
        for (var index = 3; index < pixels.Length; index += 4)
        {
            if (pixels[index] != 0)
            {
                return false;
            }
        }

        return true;
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
            // Pack failure         : historical placeholder resources may be malformed; degrade instead of crashing Shell.
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

    private static bool IsKnownV1Asset(string fileName) => fileName is
        "working.png"
        or "working_tired.png"
        or "working_annoyed.png"
        or "resting.png"
        or "offline.png";
}
