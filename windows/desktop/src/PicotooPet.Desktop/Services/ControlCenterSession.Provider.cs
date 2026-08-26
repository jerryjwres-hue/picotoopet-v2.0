using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把固定 Provider 状态、人工额度确认、会话读取与紧急取消接入安全配对会话。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<ProviderStatusRecord> GetProviderStatusAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateProviderClient();
        return await client.GetStatusAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderStatusRecord> GetClaudeCodeProviderStatusAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateProviderClient();
        return await client.GetClaudeCodeStatusAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderSessionRecord[]> GetProviderSessionsAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateProviderClient();
        return await client.GetSessionsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderUsageConfirmationRecord> ConfirmProviderUsageAsync(
        string handoffId,
        string usageStatus,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        ArgumentException.ThrowIfNullOrWhiteSpace(usageStatus);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateProviderClient();
        return await client.ConfirmUsageAsync(
            handoffId,
            usageStatus,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderSessionRecord> CancelProviderSessionAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateProviderClient();
        return await client.CancelSessionAsync(
            sessionId,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    private MacCoreProviderClient CreateProviderClient()
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
        return MacCoreProviderClient.Create(baseUri, token);
    }
}