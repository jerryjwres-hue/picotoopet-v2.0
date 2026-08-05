using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把低频 Return 观察与本地合同演练接入当前安全配对会话。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>读取最多一百条 Return 固定安全投影。</summary>
    public async Task<ReturnRecord[]> GetReturnsAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateReturnClient();
        return await client.GetReturnsAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>使用调用方幂等键运行服务器自有零变更 Return 合同演练。</summary>
    public async Task<ReturnRecord> RunReturnSelfTestAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateReturnClient();
        return await client.RunSelfTestAsync(
            handoffId,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    private MacCoreReturnClient CreateReturnClient()
    {
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }

        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException(
                "尚未配对 Mac Core；设备令牌只允许从 Credential Manager 读取。");
        }
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("当前 Mac Core 地址格式无效。");
        }
        return MacCoreReturnClient.Create(baseUri, token);
    }
}
