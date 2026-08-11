using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>读取发布程序集内置的受信模型 Manifest；运行时不接受用户/model supplied 文件名。</summary>
public static class ComfyModelManifestCatalog
{
    private const string ResourceName = "PicotooPet.Desktop.Core.Production.Resources.model_manifest.json";
    private static readonly Lazy<ComfyModelManifest> Cached = new(LoadCore);

    /// <summary>返回只读的受信模型清单。</summary>
    public static ComfyModelManifest Load() => Cached.Value;

    private static ComfyModelManifest LoadCore()
    {
        var assembly = typeof(ComfyModelManifestCatalog).Assembly;
        using var stream = assembly.GetManifestResourceStream(ResourceName)
            ?? throw new InvalidOperationException($"缺少内置模型 Manifest：{ResourceName}");
        var manifest = JsonSerializer.Deserialize<ComfyModelManifest>(stream)
            ?? throw new InvalidDataException("COMFY_MODEL_MANIFEST_INVALID");
        if (manifest.Models is null || manifest.Models.Count == 0)
        {
            throw new InvalidDataException("COMFY_MODEL_MANIFEST_EMPTY");
        }
        return manifest;
    }
}

/// <summary>只投影 preflight 所需的模型根目录与哈希字段。</summary>
public sealed record ComfyModelManifest(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("model_root")] string ModelRoot,
    [property: JsonPropertyName("models")] IReadOnlyList<ComfyPinnedModel> Models);

/// <summary>单个受信模型事实。</summary>
public sealed record ComfyPinnedModel(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("filename")] string Filename,
    [property: JsonPropertyName("destination")] string Destination,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("required")] bool Required);
