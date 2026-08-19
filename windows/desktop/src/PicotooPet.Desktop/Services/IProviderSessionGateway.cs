using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows 只保留 Provider 状态、人工额度确认、会话读取与紧急取消。</summary>
public interface IProviderSessionGateway
{
    Task<ProviderStatusRecord> GetStatusAsync(CancellationToken cancellationToken);

    Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken);

    Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken);

    Task<ProviderUsageConfirmationRecord> ConfirmUsageAsync(
        string handoffId,
        string usageStatus,
        string idempotencyKey,
        CancellationToken cancellationToken);

    Task<ProviderSessionRecord> CancelSessionAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken);
}

/// <summary>把 ControlCenterSession 限缩为只读/确认/紧急取消 Provider 网关。</summary>
public sealed class ControlCenterProviderGateway : IProviderSessionGateway
{
    private readonly ControlCenterSession _session;

    public ControlCenterProviderGateway(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public Task<ProviderStatusRecord> GetStatusAsync(CancellationToken cancellationToken) =>
        _session.GetProviderStatusAsync(cancellationToken);

    public Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken) =>
        _session.GetHandoffsAsync(cancellationToken);

    public Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken) =>
        _session.GetProviderSessionsAsync(cancellationToken);

    public Task<ProviderUsageConfirmationRecord> ConfirmUsageAsync(
        string handoffId,
        string usageStatus,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.ConfirmProviderUsageAsync(
            handoffId,
            usageStatus,
            idempotencyKey,
            cancellationToken);

    public Task<ProviderSessionRecord> CancelSessionAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.CancelProviderSessionAsync(
            sessionId,
            idempotencyKey,
            cancellationToken);
}