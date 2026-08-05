using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>审批中心使用的有界读取和摘要绑定决策。</summary>
public sealed partial class ControlCenterSession
{
    /// <summary>读取 Mac Core 当前审批快照。</summary>
    public Task<ApprovalRecord[]> GetApprovalsAsync(CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        return coordinator.GetApprovalsAsync(cancellationToken);
    }

    /// <summary>批准或拒绝当前摘要，并刷新任务快照以反映服务端终态。</summary>
    public async Task<ApprovalRecord> DecideApprovalAsync(
        ApprovalRecord approval,
        string decision,
        string reason,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(approval);
        if (decision is not ("approve" or "reject"))
        {
            throw new ArgumentOutOfRangeException(nameof(decision), decision, "未知审批决策。");
        }
        if (string.IsNullOrWhiteSpace(reason))
        {
            throw new ArgumentException("审批原因不能为空。", nameof(reason));
        }

        var coordinator = _coordinator
            ?? throw new InvalidOperationException("尚未连接 Mac Core。");
        var result = await coordinator.DecideApprovalAsync(
            approval.ApprovalId,
            new ApprovalDecisionRequest(decision, approval.RequestDigest, reason.Trim()),
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
        await RefreshAsync(cancellationToken).ConfigureAwait(false);
        return result;
    }
}
