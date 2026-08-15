using System.Collections.Concurrent;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace PicotooPet.Desktop.Views.Controls;

/// <summary>只读取固定应用目录中的茅台 Q 版 PNG；失败时回退到已打包资源。</summary>
internal static class MaotaiPetAssetLoader
{
    private static readonly ConcurrentDictionary<string, ImageSource> Cache = new(StringComparer.OrdinalIgnoreCase);

    // Asset root       : fixed application-owned UI directory; no arbitrary user-file enumeration occurs.
    private static readonly string AssetRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "ui-assets",
        "maotai",
        "v1");

    /// <summary>加载已知 PNG；本地覆盖不存在/损坏时安全回退到程序集资源。</summary>
    public static ImageSource LoadOrFallback(
        string fileName,
        Uri fallbackUri)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        ArgumentNullException.ThrowIfNull(fallbackUri);

        var cacheKey = $"{fileName}|{fallbackUri}";
        return Cache.GetOrAdd(
            cacheKey,
            _ => TryLoadLocal(fileName) ?? LoadPackResource(fallbackUri));
    }

    private static ImageSource? TryLoadLocal(string fileName)
    {
        if (!IsKnownAsset(fileName))
        {
            return null;
        }

        var fullPath = Path.Combine(AssetRoot, fileName);
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
            or ArgumentException)
        {
            // Asset failure    : decorative art must never take down Shell/Core/Worker/task flows.
            return null;
        }
    }

    private static ImageSource LoadPackResource(Uri fallbackUri)
    {
        var bitmap = new BitmapImage();
        bitmap.BeginInit();
        bitmap.CacheOption = BitmapCacheOption.OnLoad;
        bitmap.UriSource   = fallbackUri;
        bitmap.EndInit();
        bitmap.Freeze();
        return bitmap;
    }

    private static bool IsKnownAsset(string fileName) => fileName is
        "working.png"
        or "working_tired.png"
        or "working_annoyed.png"
        or "resting.png"
        or "offline.png";
}
