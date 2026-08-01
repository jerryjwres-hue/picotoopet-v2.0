using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>单写入锁保护的桌面状态仓库；界面只接收不可变快照。</summary>
public sealed class AppStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly object _gate = new();
    private readonly Dictionary<string, TaskRecord> _tasks = new(StringComparer.Ordinal);
    private ConnectionState _connectionState = ConnectionState.Offline;
    private string? _lastError;
    private long _lastSequence;

    /// <summary>状态提交后发布新的不可变快照。</summary>
    public event EventHandler<AppSnapshot>? SnapshotChanged;

    /// <summary>当前快照。</summary>
    public AppSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return CreateSnapshot(taskReset: false, changedTask: null);
            }
        }
    }

    /// <summary>用 REST 初始数据替换任务集合，并通知界面执行一次完整差异归并。</summary>
    public void ReplaceTasks(IEnumerable<TaskRecord> tasks)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        AppSnapshot snapshot;
        lock (_gate)
        {
            _tasks.Clear();
            foreach (var task in tasks)
            {
                _tasks[task.TaskId] = task;
            }
            snapshot = CreateSnapshot(taskReset: true, changedTask: null);
        }
        PublishSnapshot(snapshot);
    }

    /// <summary>归并一个 REST 返回任务，避免为单条变化重建整个状态集合。</summary>
    public void UpsertTask(TaskRecord task)
    {
        ArgumentNullException.ThrowIfNull(task);
        AppSnapshot snapshot;
        lock (_gate)
        {
            _tasks[task.TaskId] = task;
            snapshot = CreateSnapshot(taskReset: false, changedTask: task);
        }
        PublishSnapshot(snapshot);
    }

    /// <summary>归并单个顺序事件；旧序号和重复事件不会回滚状态。</summary>
    public bool Apply(
        EventEnvelope envelope,
        Predicate<TaskRecord>? includeTask = null)
    {
        ArgumentNullException.ThrowIfNull(envelope);
        AppSnapshot snapshot;
        TaskRecord? changedTask = null;
        lock (_gate)
        {
            if (envelope.Sequence <= _lastSequence)
            {
                return false;
            }
            if (envelope.TryGetTask(JsonOptions, out var task)
                && task is not null
                && (includeTask is null || includeTask(task)))
            {
                _tasks[task.TaskId] = task;
                changedTask = task;
            }
            // 即使过滤任务负载也确认事件序号，避免重连时反复重放同一诊断事件。
            _lastSequence = envelope.Sequence;
            snapshot = CreateSnapshot(taskReset: false, changedTask);
        }
        PublishSnapshot(snapshot);
        return true;
    }

    /// <summary>更新连接状态和可选错误摘要。</summary>
    public void SetConnection(ConnectionState state, string? error = null)
    {
        AppSnapshot snapshot;
        lock (_gate)
        {
            _connectionState = state;
            _lastError       = error;
            snapshot = CreateSnapshot(taskReset: false, changedTask: null);
        }
        PublishSnapshot(snapshot);
    }

    private AppSnapshot CreateSnapshot(bool taskReset, TaskRecord? changedTask) => new(
        _connectionState,
        _tasks.Values
            .OrderByDescending(task => task.CreatedAt)
            .ToArray(),
        _lastError,
        _lastSequence,
        taskReset,
        changedTask);

    private void PublishSnapshot(AppSnapshot snapshot) =>
        SnapshotChanged?.Invoke(this, snapshot);
}

/// <summary>界面层消费的不可变应用快照，并携带增量变化提示。</summary>
public sealed record AppSnapshot(
    ConnectionState ConnectionState,
    IReadOnlyList<TaskRecord> Tasks,
    string? LastError,
    long LastSequence,
    bool TaskReset,
    TaskRecord? ChangedTask);
