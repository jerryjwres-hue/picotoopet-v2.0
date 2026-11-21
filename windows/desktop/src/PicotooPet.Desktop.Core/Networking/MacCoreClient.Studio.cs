using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>原 2.3 客户端对 V3.1 StoryPack 的只读、受限适配；不新增生产执行器。</summary>
public sealed partial class MacCoreClient
{
    private const int MaxStoryPackRequestBytes = 128 * 1024;
    private const int MaxStudioPreviewResponseBytes = 512 * 1024;

    /// <summary>让现有 Windows Studio 使用 2.3 Mac Core 预览；不创建 Episode/Lease/GPU 作业。</summary>
    public Task<JsonElement> PreviewStudioStoryPackAsync(
        JsonElement storyPack,
        CancellationToken cancellationToken = default)
    {
        if (storyPack.ValueKind != JsonValueKind.Object)
        {
            throw new ArgumentException("StoryPack 必须是 JSON 对象。", nameof(storyPack));
        }

        // 在网络调用之前限制请求体；不能用旧 V3.1 的 Executor/Owner Bearer 代替本接口。
        if (Encoding.UTF8.GetByteCount(storyPack.GetRawText()) > MaxStoryPackRequestBytes)
        {
            throw new ArgumentException("StoryPack 不能超过 128 KiB。", nameof(storyPack));
        }

        // 共用原 MacCoreClient 的设备 Bearer、Trace、响应限额及错误处理。
        return SendAsync<JsonElement>(
            HttpMethod.Post,
            "api/v1/studio/storypacks/preview",
            storyPack,
            "studio.storypack.preview.readonly",
            null,
            cancellationToken,
            MaxStudioPreviewResponseBytes);
    }
}
