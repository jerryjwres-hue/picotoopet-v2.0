using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>复用唯一已配对的 Core 通道；登记声明不等于 Owner 审批或 GPU 权限。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<StudioWindowsClaimReceipt> RegisterStudioWindowsLoraAsync(
        string projectId, string sha256, long sizeBytes,
        StudioWindowsByteEvidence evidence, CancellationToken cancellationToken)
    {
        // 01. 每次独立用户操作都从现有 Credential Manager 中读取配对凭据。
        await using var client = CreateStudioRegistryClient();
        return await client.RegisterStudioWindowsLoraAsync(
            projectId, sha256, sizeBytes, evidence, cancellationToken).ConfigureAwait(false);
    }

    public async Task<StudioOwnerApprovalRequestReceipt> RequestStudioAssetOwnerApprovalAsync(
        string artifactId, string sha256, StudioWindowsByteEvidence? evidence,
        CancellationToken cancellationToken)
    {
        // 02. 这只提交「请求」；Mac Core 决定请求有效性，Owner 在审批中心决定。
        await using var client = CreateStudioRegistryClient();
        return await client.RequestStudioAssetOwnerApprovalAsync(
            artifactId, sha256, evidence, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreClient CreateStudioRegistryClient()
    {
        ThrowIfDisposed();
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        ValidateConnectionInput(baseUrl, token, out var baseUri);
        return MacCoreClient.Create(MacCoreClientOptions.CreateDefault(baseUri, token));
    }
}
