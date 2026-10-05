using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把只读 Frugal Coding Escalation 决策接入当前安全配对会话。</summary>
public sealed partial class ControlCenterSession : ICodingEscalationDecisionGateway
{
    public async Task<CodingEscalationDecisionRecord> GetDecisionAsync(
        string goalId,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(goalId);
        await using var client = CreateCodingEscalationClient();
        return await client.GetDecisionAsync(goalId, cancellationToken).ConfigureAwait(false);
    }

    private MacCoreCodingEscalationClient CreateCodingEscalationClient()
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
        return MacCoreCodingEscalationClient.Create(baseUri, token);
    }
}
