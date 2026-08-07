using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把 Phase 10D-B Review/Adoption 操作接入当前安全配对会话。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<ProviderReviewRecord> GetProviderReviewAsync(
        string sessionId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        await using var client = CreateProviderReviewClient();
        return await client.GetReviewAsync(sessionId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderReviewRecord> AcceptProviderReviewAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateProviderReviewClient();
        return await client.AcceptAsync(sessionId, idempotencyKey, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderReviewRecord> RejectProviderReviewAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateProviderReviewClient();
        return await client.RejectAsync(sessionId, idempotencyKey, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProviderAdoptionCandidateRecord[]> GetProviderAdoptionCandidatesAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateProviderReviewClient();
        return await client.GetCandidatesAsync(cancellationToken).ConfigureAwait(false);
    }

    private MacCoreProviderReviewClient CreateProviderReviewClient()
    {
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core；设备令牌只允许从 Credential Manager 读取。");
        }
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("当前 Mac Core 地址格式无效。");
        }
        return MacCoreProviderReviewClient.Create(baseUri, token);
    }
}
