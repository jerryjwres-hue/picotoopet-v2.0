using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>事件序号应用结果；跳跃事件不得静默推进状态。</summary>
public enum SequenceApplyResult
{
    Applied,
    Duplicate,
    GapDetected,
}

/// <summary>独立维护任务快照、增量变化和最后连续事件序号。</summary>
public sealed class TaskStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly object _gate = new();
    private readonly Dictionary<string, TaskRecord> _tasks = new(StringComparer.Ordinal);
    private long _lastSequence;

    /// <summary>任务状态提交后发布新的不可变快照。</summary>
    public event EventHandler<TaskStateSnapshot>? SnapshotChanged;

    /// <summary>当前任务快照。</summary>
    public TaskStateSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return CreateSnapshot(taskReset: false, changedTask: null);
            }
        }
    }

    /// <summary>用 REST 初始数据替换任务集合。</summary>
    public void ReplaceTasks(IEnumerable<TaskRecord> tasks)
    {
        ArgumentNullException.ThrowIfNull(tasks);

        TaskStateSnapshot snapshot;
        lock (_gate)
        {
            ReplaceTasksLocked(tasks);
            snapshot = CreateSnapshot(taskReset: true, changedTask: null);
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>用 REST 恢复快照并确认触发恢复的事件序号。</summary>
    public void ReloadTasksAtSequence(
        IEnumerable<TaskRecord> tasks,
        long confirmedSequence)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        if (confirmedSequence < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(confirmedSequence),
                "确认序号不得小于零。");
        }

        TaskStateSnapshot snapshot;
        lock (_gate)
        {
            ReplaceTasksLocked(tasks);
            _lastSequence = Math.Max(_lastSequence, confirmedSequence);
            snapshot = CreateSnapshot(taskReset: true, changedTask: null);
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>归并一个 REST 返回任务；REST 响应可权威改变可恢复隐藏状态。</summary>
    public void UpsertTask(TaskRecord task)
    {
        ArgumentNullException.ThrowIfNull(task);

        TaskStateSnapshot snapshot;
        lock (_gate)
        {
            _tasks[task.TaskId] = task;
            snapshot = CreateSnapshot(taskReset: false, changedTask: task);
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>只应用连续执行事件；队列事件不得覆盖 REST 已确认的用户隐藏状态。</summary>
    public SequenceApplyResult Apply(
        EventEnvelope envelope,
        Predicate<TaskRecord>? includeTask = null)
    {
        ArgumentNullException.ThrowIfNull(envelope);

        TaskStateSnapshot snapshot;
        TaskRecord? changedTask = null;
        lock (_gate)
        {
            if (envelope.Sequence <= _lastSequence)
            {
                return SequenceApplyResult.Duplicate;
            }
            if (envelope.Sequence != _lastSequence + 1)
            {
                return SequenceApplyResult.GapDetected;
            }
            if (envelope.TryGetTask(JsonOptions, out var task)
                && task is not null
                && (includeTask is null || includeTask(task)))
            {
                if (_tasks.TryGetValue(task.TaskId, out var existing) && existing.IsHidden)
                {
                    task = task with { IsHidden = true };
                }
                _tasks[task.TaskId] = task;
                changedTask = task;
            }

            _lastSequence = envelope.Sequence;
            snapshot = CreateSnapshot(taskReset: false, changedTask);
        }
        SnapshotChanged?.Invoke(this, snapshot);
        return SequenceApplyResult.Applied;
    }

    private void ReplaceTasksLocked(IEnumerable<TaskRecord> tasks)
    {
        _tasks.Clear();
        foreach (var task in tasks)
        {
            _tasks[task.TaskId] = task;
        }
    }

    private TaskStateSnapshot CreateSnapshot(bool taskReset, TaskRecord? changedTask) => new(
        _tasks.Values
            .OrderByDescending(task => task.CreatedAt)
            .ToArray(),
        _lastSequence,
        taskReset,
        changedTask);
}
