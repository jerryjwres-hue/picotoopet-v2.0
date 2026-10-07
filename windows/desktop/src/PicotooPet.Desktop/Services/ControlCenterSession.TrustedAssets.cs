using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>受信图片导入入口：复用当前已配对 Core 凭据，不持久化任何新配置，也不发送源路径。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<TrustedAssetImportResult> ImportTrustedImageAsync(
        string scopeKind,
        string scopeId,
        string sourcePath,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        string macBaseUrl;
        lock (_snapshotGate)
        {
            macBaseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core，无法导入资产。");
        }
        if (!Uri.TryCreate(macBaseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("已保存的 Mac Core 地址无效。");
        }

        var inputRoot = Path.Combine(ProductionLocalEnvironment.ResolveComfyDataRoot(), "input");
        await using var client = MacCoreTrustedAssetClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
        var service = new TrustedAssetIngressService(inputRoot, client);
        return await service.ImportImageAsync(scopeKind, scopeId, sourcePath, cancellationToken)
            .ConfigureAwait(false);
    }
}
