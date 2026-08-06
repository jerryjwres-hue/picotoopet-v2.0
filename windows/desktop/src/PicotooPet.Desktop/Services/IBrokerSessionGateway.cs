using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Phase 10B-B WPF 只能使用的 Broker Session 安全投影与固定动作。</summary>
public interface IBrokerSessionGateway
{
    /// <summary>读取 Handoff 安全投影，由 ViewModel 过滤 approved 状态。</summary>
    Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken);

    /// <summary>读取最多一百条 Broker Session 安全投影。</summary>
    Task<BrokerSessionRecord[]> GetBrokerSessionsAsync(CancellationToken cancellationToken);

    /// <summary>运行固定 Mock Broker；进度只报告不含 capability 的安全投影。</summary>
    Task<BrokerSessionRecord> RunMockBrokerAsync(
        HandoffRecord handoff,
        string idempotencyKey,
        IProgress<BrokerSessionRecord> progress,
        CancellationToken cancellationToken);

    /// <summary>取消当前固定 Broker 进程树并提交 Mac Core 取消事实。</summary>
    Task<BrokerSessionRecord> CancelBrokerAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken);
}

/// <summary>把 Control Center 运行时会话限制为 Broker 面板所需的四个动作。</summary>
public sealed class ControlCenterBrokerGateway : IBrokerSessionGateway
{
    private readonly ControlCenterSession _session;

    public ControlCenterBrokerGateway(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken) =>
        _session.GetHandoffsAsync(cancellationToken);

    public Task<BrokerSessionRecord[]> GetBrokerSessionsAsync(
        CancellationToken cancellationToken) =>
        _session.GetBrokerSessionsAsync(cancellationToken);

    public Task<BrokerSessionRecord> RunMockBrokerAsync(
        HandoffRecord handoff,
        string idempotencyKey,
        IProgress<BrokerSessionRecord> progress,
        CancellationToken cancellationToken) =>
        _session.RunMockBrokerAsync(
            handoff,
            idempotencyKey,
            progress,
            cancellationToken);

    public Task<BrokerSessionRecord> CancelBrokerAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.CancelBrokerAsync(sessionId, idempotencyKey, cancellationToken);
}
