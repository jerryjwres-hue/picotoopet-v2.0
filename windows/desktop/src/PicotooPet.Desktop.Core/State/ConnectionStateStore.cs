namespace PicotooPet.Desktop.Core.State;

/// <summary>独立维护 REST Core 可达性和 WebSocket 实时通道状态。</summary>
public sealed class ConnectionStateStore
{
    private readonly object _gate = new();
    private ConnectionSnapshot _snapshot = new(ConnectionState.Offline, null);
    private bool _coreReachable;
    private bool _coreAuthenticationFailed;
    private bool _eventAuthenticationFailed;
    private ConnectionState _eventStreamState = ConnectionState.Offline;
    private string? _coreError;
    private string? _eventError;

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

    /// <summary>兼容旧调用方直接提交聚合状态；新同步链应使用分通道方法。</summary>
    public void Set(ConnectionState state, string? error = null)
    {
        ConnectionSnapshot snapshot;
        lock (_gate)
        {
            _coreAuthenticationFailed  = state == ConnectionState.AuthenticationFailed;
            _eventAuthenticationFailed = state == ConnectionState.AuthenticationFailed;
            _coreReachable             = state == ConnectionState.Online;
            _eventStreamState          = state;
            _coreError                 = error;
            _eventError                = error;
            snapshot                   = BuildSnapshot(stateOverride: state);
            _snapshot                  = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>提交 REST Core 可达性；REST 健康时 WebSocket 故障不得把整个系统判离线。</summary>
    public void SetCoreReachability(bool reachable, string? error = null)
    {
        ConnectionSnapshot snapshot;
        lock (_gate)
        {
            _coreReachable            = reachable;
            _coreAuthenticationFailed = false;
            _coreError                = reachable ? null : error;
            snapshot                  = BuildSnapshot();
            _snapshot                 = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>提交 REST 认证失败；认证错误高于任何通道健康事实。</summary>
    public void SetCoreAuthenticationFailed(string? error = null)
    {
        ConnectionSnapshot snapshot;
        lock (_gate)
        {
            _coreReachable            = false;
            _coreAuthenticationFailed = true;
            _coreError                = error;
            snapshot                  = BuildSnapshot();
            _snapshot                 = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>提交 WebSocket 实时通道状态，但不覆盖 REST 可达性事实。</summary>
    public void SetEventStreamState(ConnectionState state, string? error = null)
    {
        ConnectionSnapshot snapshot;
        lock (_gate)
        {
            _eventStreamState          = state;
            _eventAuthenticationFailed = state == ConnectionState.AuthenticationFailed;
            _eventError                = state == ConnectionState.Online ? null : error;
            snapshot                   = BuildSnapshot();
            _snapshot                  = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    private ConnectionSnapshot BuildSnapshot(ConnectionState? stateOverride = null)
    {
        var aggregate = stateOverride ?? AggregateState();
        var realtimeDegraded = _coreReachable && _eventStreamState != ConnectionState.Online;
        string? lastError = null;
        if (_coreAuthenticationFailed || !_coreReachable)
        {
            lastError = _coreError;
        }
        else if (realtimeDegraded)
        {
            lastError = _eventError;
        }
        return new ConnectionSnapshot(
            aggregate,
            lastError,
            _coreReachable,
            _eventStreamState,
            realtimeDegraded);
    }

    private ConnectionState AggregateState()
    {
        if (_coreAuthenticationFailed || _eventAuthenticationFailed)
        {
            return ConnectionState.AuthenticationFailed;
        }
        if (_coreReachable)
        {
            return ConnectionState.Online;
        }
        return _eventStreamState switch
        {
            ConnectionState.Connecting or ConnectionState.Reconnecting => ConnectionState.Reconnecting,
            ConnectionState.Offline                                    => ConnectionState.Offline,
            _                                                          => ConnectionState.Faulted,
        };
    }
}
