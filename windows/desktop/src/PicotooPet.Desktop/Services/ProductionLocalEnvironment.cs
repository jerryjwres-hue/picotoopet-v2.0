using System.Security.Cryptography;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

/// <summary>Production executor 与最终视频合成共享的受信本地数据根和路径边界。</summary>
public static class ProductionLocalEnvironment
{
    public static string ResolveComfyDataRoot()
    {
        var candidates = new List<string>();
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var configPath = Path.Combine(appData, "ComfyUI", "config.json");
        if (File.Exists(configPath))
        {
            try
            {
                using var config = JsonDocument.Parse(File.ReadAllText(configPath));
                if (config.RootElement.TryGetProperty("basePath", out var basePath)
                    && basePath.ValueKind == JsonValueKind.String
                    && !string.IsNullOrWhiteSpace(basePath.GetString()))
                {
                    candidates.Add(basePath.GetString()!);
                }
            }
            catch (JsonException)
            {
                // 损坏 config 不扩大候选范围，只继续固定候选。
            }
        }
        candidates.AddRange(
        [
            Path.Combine(appData, "ComfyUI"),
            Path.Combine(localAppData, "ComfyUI"),
            Path.Combine(userProfile, "ComfyUI"),
            @"D:\ComfyUI",
            @"D:\PicotooPet\ComfyUI",
            @"E:\ComfyUI",
        ]);

        foreach (var candidate in candidates.Where(item => !string.IsNullOrWhiteSpace(item)))
        {
            var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(candidate));
            if (!Directory.Exists(full) || IsDesktopResourceTree(full))
            {
                continue;
            }
            if (Directory.Exists(Path.Combine(full, "models"))
                || Directory.Exists(Path.Combine(full, "custom_nodes"))
                || File.Exists(Path.Combine(full, "main.py"))
                || Directory.Exists(Path.Combine(full, "output")))
            {
                return full;
            }
        }
        throw new DirectoryNotFoundException("COMFY_DATA_ROOT_NOT_FOUND");
    }

    public static string ResolveComfyOutputRoot()
    {
        var dataRoot = ResolveComfyDataRoot();
        var outputRoot = Path.GetFullPath(Path.Combine(dataRoot, "output"));
        if (!Directory.Exists(outputRoot))
        {
            throw new DirectoryNotFoundException("COMFY_OUTPUT_ROOT_NOT_FOUND");
        }
        AssertNoLinkEscape(dataRoot, outputRoot);
        return outputRoot;
    }

    public static string ResolveUnderRoot(
        string root,
        string relative,
        bool requireExistingFile)
    {
        if (string.IsNullOrWhiteSpace(relative)
            || relative.Length > 500
            || Path.IsPathRooted(relative)
            || relative.Contains(':', StringComparison.Ordinal))
        {
            throw new InvalidDataException("PRODUCTION_PATH_MUST_BE_BOUNDED_RELATIVE");
        }
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(Path.Combine(fullRoot, relative));
        if (!full.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("PRODUCTION_PATH_ESCAPE");
        }
        if (requireExistingFile && !File.Exists(full))
        {
            throw new FileNotFoundException("TRUSTED_PRODUCTION_FILE_MISSING");
        }
        return full;
    }

    public static void AssertNoLinkEscape(string root, string path)
    {
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        var fullPath = Path.GetFullPath(path);
        var rootPrefix = fullRoot + Path.DirectorySeparatorChar;
        if (!string.Equals(fullPath, fullRoot, StringComparison.OrdinalIgnoreCase)
            && !fullPath.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("PRODUCTION_PATH_ESCAPE");
        }

        var current = new FileInfo(fullPath);
        if (current.Exists && IsReparsePoint(current.Attributes))
        {
            throw new InvalidDataException("PRODUCTION_REPARSE_POINT_FORBIDDEN");
        }
        var parent = current.Directory;
        while (parent is not null
               && (string.Equals(parent.FullName, fullRoot, StringComparison.OrdinalIgnoreCase)
                   || parent.FullName.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase)))
        {
            if (parent.Exists && IsReparsePoint(parent.Attributes))
            {
                throw new InvalidDataException("PRODUCTION_REPARSE_POINT_FORBIDDEN");
            }
            if (string.Equals(parent.FullName, fullRoot, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            parent = parent.Parent;
        }
    }

    public static async Task<string> Sha256FileAsync(
        string path,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 1024 * 1024,
            options: FileOptions.Asynchronous | FileOptions.SequentialScan);
        var digest = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
        return Convert.ToHexString(digest).ToLowerInvariant();
    }

    public static bool IsOrdinaryFile(string path)
    {
        if (!File.Exists(path))
        {
            return false;
        }
        var attributes = File.GetAttributes(path);
        return (attributes & FileAttributes.Directory) == 0 && !IsReparsePoint(attributes);
    }

    private static bool IsReparsePoint(FileAttributes attributes) =>
        (attributes & FileAttributes.ReparsePoint) != 0;

    private static bool IsDesktopResourceTree(string path) =>
        path.Replace('/', '\\').Contains("\\resources\\ComfyUI", StringComparison.OrdinalIgnoreCase);
}
