using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Services;

/// <summary>供本机审片对话框使用的文件和勾选项。</summary>
public sealed record LocalBatchProfile(
    string Receipt,
    string EpisodeId = "",
    string Title = "",
    string Prefix = "",
    string EpisodeFile = "",
    string RetakesFile = "",
    string CutPlanFile = "",
    string CutVideoFile = "",
    bool Thumbnails = true,
    bool Probe = true,
    int Version = 1)
{
    private const int Limit = 64 * 1024;

    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        WriteIndented = true,
    };

    public static LocalBatchProfile Load(string path)
    {
        var file = new FileInfo(path);
        using var stream = file.OpenRead();
        if (stream.Length > Limit) throw new InvalidDataException("本地审片配置不能超过 64 KB。");
        var profile = JsonSerializer.Deserialize<LocalBatchProfile>(stream, Options)
            ?? throw new InvalidDataException("本地审片配置为空。");
        if (profile.Version != 1 || string.IsNullOrWhiteSpace(profile.Receipt))
            throw new InvalidDataException("需要版本 1 的本地审片配置和完成回执路径。");
        return profile.MapPaths(value => Resolve(value, file.DirectoryName!));
    }

    public static void Save(string path, LocalBatchProfile profile)
    {
        var file = new FileInfo(path);
        var directory = file.DirectoryName!;
        var relative = profile.MapPaths(value => string.IsNullOrWhiteSpace(value)
            ? ""
            : Path.GetRelativePath(directory, Resolve(value, directory)));
        var data = JsonSerializer.SerializeToUtf8Bytes(relative, Options);
        if (data.Length > Limit) throw new InvalidDataException("本地审片配置不能超过 64 KB。");
        var staging = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            File.WriteAllBytes(staging, data);
            File.Move(staging, file.FullName, overwrite: true);
        }
        finally
        {
            File.Delete(staging);
        }
    }

    private static string Resolve(string? value, string directory)
    {
        if (string.IsNullOrWhiteSpace(value)) return "";
        var path = Path.GetFullPath(value, directory);
        if (path.StartsWith(@"\\", StringComparison.Ordinal))
            throw new InvalidDataException("本地审片配置需要 Windows 本机文件路径。");
        return path;
    }

    private LocalBatchProfile MapPaths(Func<string, string> map) => this with
    {
        Receipt = map(Receipt),
        EpisodeFile = map(EpisodeFile),
        RetakesFile = map(RetakesFile),
        CutPlanFile = map(CutPlanFile),
        CutVideoFile = map(CutVideoFile),
    };
}
