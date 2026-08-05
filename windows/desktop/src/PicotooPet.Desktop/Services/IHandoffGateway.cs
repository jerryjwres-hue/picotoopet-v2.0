using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>云端开发页允许调用的完整 Phase 10A 操作表面。</summary>
public interface IHandoffGateway
{
    /// <summary>读取服务端固定模板。</summary>
    Task<HandoffTemplateRecord[]> GetTemplatesAsync(
        CancellationToken cancellationToken);

    /// <summary>读取最近 Handoff 安全投影。</summary>
    Task<HandoffRecord[]> GetHandoffsAsync(
        CancellationToken cancellationToken);

    /// <summary>使用同一幂等键准备确定性 Handoff。</summary>
    Task<HandoffRecord> PrepareAsync(
        HandoffPrepareRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken);

    /// <summary>使用同一幂等键提交摘要绑定审批。</summary>
    Task<HandoffRecord> SubmitApprovalAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken);
}

/// <summary>把 ControlCenterSession 限缩为云端开发页可见的 Phase 10A 网关。</summary>
public sealed class ControlCenterHandoffGateway : IHandoffGateway
{
    private readonly ControlCenterSession _session;

    public ControlCenterHandoffGateway(ControlCenterSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public Task<HandoffTemplateRecord[]> GetTemplatesAsync(
        CancellationToken cancellationToken) =>
        _session.GetHandoffTemplatesAsync(cancellationToken);

    public Task<HandoffRecord[]> GetHandoffsAsync(
        CancellationToken cancellationToken) =>
        _session.GetHandoffsAsync(cancellationToken);

    public Task<HandoffRecord> PrepareAsync(
        HandoffPrepareRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.PrepareHandoffAsync(
            request,
            idempotencyKey,
            cancellationToken);

    public Task<HandoffRecord> SubmitApprovalAsync(
        string handoffId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.SubmitHandoffApprovalAsync(
            handoffId,
            idempotencyKey,
            cancellationToken);
}
