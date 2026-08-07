using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows Phase 10D-A 只允许调用的固定 Codex Provider 操作表面。</summary>
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

    Task<ProviderSessionRecord> StartSessionAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken);

    Task<ProviderSessionRecord> CancelSessionAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken);
}

/// <summary>把 ControlCenterSession 限缩为 Phase 10D-A Provider 网关。</summary>
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

    public Task<ProviderSessionRecord> StartSessionAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.StartProviderSessionAsync(
            handoffId,
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
