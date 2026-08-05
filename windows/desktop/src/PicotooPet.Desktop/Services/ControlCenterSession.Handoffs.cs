using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把低频 Handoff 操作接入当前安全配对会话。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>读取 Mac Core 发布的固定 Handoff 模板。</summary>
    public async Task<HandoffTemplateRecord[]> GetHandoffTemplatesAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateHandoffClient();
        return await client.GetTemplatesAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>读取最多一百条 Handoff 安全投影。</summary>
    public async Task<HandoffRecord[]> GetHandoffsAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateHandoffClient();
        return await client.GetHandoffsAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>使用固定请求合同和调用方幂等键准备 Handoff。</summary>
    public async Task<HandoffRecord> PrepareHandoffAsync(
        HandoffPrepareRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateHandoffClient();
        return await client.PrepareAsync(
            request,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>读取单个 Handoff 的固定安全投影。</summary>
    public async Task<HandoffRecord> GetHandoffAsync(
        string handoffId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        await using var client = CreateHandoffClient();
        return await client.GetHandoffAsync(
            handoffId,
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>使用调用方幂等键把 Handoff 摘要提交到 Approval Center。</summary>
    public async Task<HandoffRecord> SubmitHandoffApprovalAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(handoffId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        await using var client = CreateHandoffClient();
        return await client.SubmitApprovalAsync(
            handoffId,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    private MacCoreHandoffClient CreateHandoffClient()
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
        return MacCoreHandoffClient.Create(baseUri, token);
    }
}
