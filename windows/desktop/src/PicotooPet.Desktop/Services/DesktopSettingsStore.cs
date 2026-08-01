using System.Text.Json;

namespace PicotooPet.Desktop.Services;

/// <summary>仅保存非敏感桌面设置；Token 永不进入此文件。</summary>
public sealed class DesktopSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };
    private readonly string _path;

    /// <summary>创建设置文件存储。</summary>
    public DesktopSettingsStore(string path)
    {
        _path = path;
    }

    /// <summary>读取设置；文件不存在时使用已确认的 Mac 局域网地址。</summary>
    public async Task<DesktopSettings> LoadAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_path))
        {
            return DesktopSettings.Default;
        }
        await using var stream = File.OpenRead(_path);
        return await JsonSerializer.DeserializeAsync<DesktopSettings>(
            stream,
            JsonOptions,
            cancellationToken) ?? DesktopSettings.Default;
    }

    /// <summary>使用临时文件和原子替换保存非敏感设置。</summary>
    public async Task SaveAsync(DesktopSettings settings, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_path) ?? ".");
        var temporary = _path + ".tmp";
        await using (var stream = File.Create(temporary))
        {
            await JsonSerializer.SerializeAsync(
                stream,
                settings,
                JsonOptions,
                cancellationToken);
        }
        File.Move(temporary, _path, overwrite: true);
    }
}

/// <summary>可安全落盘的桌面设置。</summary>
public sealed record DesktopSettings(string MacBaseUrl)
{
    public static DesktopSettings Default { get; } = new("http://192.168.1.161:8766");
}
