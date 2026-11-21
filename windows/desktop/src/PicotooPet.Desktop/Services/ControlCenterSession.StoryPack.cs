using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows Studio 复用既有配对会话；StoryPack 预览不创建新身份或生产执行器。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>只调用 Mac Core 的 JSON StoryPack 预览接口；不授予 Owner、GPU 或任务队列权限。</summary>
    public async Task<JsonElement> PreviewStudioStoryPackAsync(
        JsonElement storyPack,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();

        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }

        // 设备令牌仅从既有 Credential Manager 读取，不写日志、文件或 UI。
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        ValidateConnectionInput(baseUrl, token, out var baseUri);

        await using var client = MacCoreClient.Create(
            MacCoreClientOptions.CreateDefault(baseUri, token));
        return await client.PreviewStudioStoryPackAsync(storyPack, cancellationToken)
            .ConfigureAwait(false);
    }
}
