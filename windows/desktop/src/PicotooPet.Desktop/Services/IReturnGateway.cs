using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Return 面板唯一可访问的 Phase 10B-A 受限操作表面。</summary>
public interface IReturnGateway
{
    /// <summary>读取最近 Handoff 安全投影，以筛选 approved 记录。</summary>
    Task<HandoffRecord[]> GetHandoffsAsync(
        CancellationToken cancellationToken);

    /// <summary>读取最近 Return 安全投影。</summary>
    Task<ReturnRecord[]> GetReturnsAsync(
        CancellationToken cancellationToken);

    /// <summary>使用同一幂等键运行服务器自有的零变更 Return 合同演练。</summary>
    Task<ReturnRecord> RunReturnSelfTestAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken);
}

/// <summary>把 ControlCenterSession 限缩为 Return 面板可见的 Phase 10B-A 网关。</summary>
public sealed class ControlCenterReturnGateway : IReturnGateway
{
    private readonly ControlCenterSession _session;

    public ControlCenterReturnGateway(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public Task<HandoffRecord[]> GetHandoffsAsync(
        CancellationToken cancellationToken) =>
        _session.GetHandoffsAsync(cancellationToken);

    public Task<ReturnRecord[]> GetReturnsAsync(
        CancellationToken cancellationToken) =>
        _session.GetReturnsAsync(cancellationToken);

    public Task<ReturnRecord> RunReturnSelfTestAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.RunReturnSelfTestAsync(
            handoffId,
            idempotencyKey,
            cancellationToken);
}
