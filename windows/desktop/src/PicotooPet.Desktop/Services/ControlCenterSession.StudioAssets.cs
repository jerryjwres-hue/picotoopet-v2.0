using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>复用已配对的安全 Core 通道，仅发送明确确认的资产副本。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<string> ImportStudioAssetAsync(
        string projectId, string role, string mediaType, byte[] data,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }

        // 设备 Bearer 仍由既有凭据管理器读取，永不显示或写入资产回执。
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        ValidateConnectionInput(baseUrl, token, out var baseUri);

        await using var client = MacCoreClient.Create(
            MacCoreClientOptions.CreateDefault(baseUri, token));
        return await client.ImportStudioAssetAsync(projectId, role, mediaType, data, cancellationToken)
            .ConfigureAwait(false);
    }
}
