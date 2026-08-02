using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>独立维护 Mac Worker 可用性；未知或旧服务一律视为未部署。</summary>
public sealed class WorkerStateStore
{
    private readonly object _gate = new();
    private WorkerSnapshot _snapshot = WorkerSnapshot.NotDeployed;

    /// <summary>Worker 状态提交后发布新的不可变快照。</summary>
    public event EventHandler<WorkerSnapshot>? SnapshotChanged;

    /// <summary>当前 Worker 快照。</summary>
    public WorkerSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return _snapshot;
            }
        }
    }

    /// <summary>提交服务端返回的 Worker 状态。</summary>
    public void Set(WorkerStatusResponse response)
    {
        ArgumentNullException.ThrowIfNull(response);
        var snapshot = new WorkerSnapshot(
            response.SchemaVersion,
            response.Available,
            response.State,
            response.Reason,
            response.WorkerId,
            response.SupportedTaskTypes,
            response.ObservedAt);
        SetSnapshot(snapshot);
    }

    /// <summary>端点缺失或响应不兼容时保守降级为未部署。</summary>
    public void SetNotDeployed(string? reason = null) =>
        SetSnapshot(WorkerSnapshot.NotDeployed with
        {
            Reason = string.IsNullOrWhiteSpace(reason)
                ? WorkerSnapshot.NotDeployed.Reason
                : reason,
            ObservedAt = DateTimeOffset.UtcNow,
        });

    private void SetSnapshot(WorkerSnapshot snapshot)
    {
        lock (_gate)
        {
            _snapshot = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }
}
