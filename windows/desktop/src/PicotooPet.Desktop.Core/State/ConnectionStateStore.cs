namespace PicotooPet.Desktop.Core.State;

/// <summary>独立维护连接状态和最近错误摘要。</summary>
public sealed class ConnectionStateStore
{
    private readonly object _gate = new();
    private ConnectionSnapshot _snapshot = new(ConnectionState.Offline, null);

    /// <summary>连接状态提交后发布新的不可变快照。</summary>
    public event EventHandler<ConnectionSnapshot>? SnapshotChanged;

    /// <summary>当前连接快照。</summary>
    public ConnectionSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return _snapshot;
            }
        }
    }

    /// <summary>原子提交连接状态和可选错误摘要。</summary>
    public void Set(ConnectionState state, string? error = null)
    {
        ConnectionSnapshot snapshot;
        lock (_gate)
        {
            snapshot  = new ConnectionSnapshot(state, error);
            _snapshot = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }
}
