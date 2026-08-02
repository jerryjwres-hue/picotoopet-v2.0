using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>兼容现有界面的状态门面；实际状态由 focused store 独立维护。</summary>
public sealed class AppStateStore
{
    /// <summary>使用默认 focused store 创建兼容门面。</summary>
    public AppStateStore()
        : this(
            new ConnectionStateStore(),
            new CapabilityStateStore(),
            new WorkerStateStore(),
            new TaskStateStore())
    {
    }

    /// <summary>保留 Slice A 三仓库构造器，并默认使用保守 Worker 状态。</summary>
    public AppStateStore(
        ConnectionStateStore connectionStore,
        CapabilityStateStore capabilityStore,
        TaskStateStore taskStore)
        : this(connectionStore, capabilityStore, new WorkerStateStore(), taskStore)
    {
    }

    /// <summary>使用显式 focused store 创建可测试门面。</summary>
    public AppStateStore(
        ConnectionStateStore connectionStore,
        CapabilityStateStore capabilityStore,
        WorkerStateStore workerStore,
        TaskStateStore taskStore)
    {
        ConnectionStore = connectionStore ?? throw new ArgumentNullException(nameof(connectionStore));
        CapabilityStore = capabilityStore ?? throw new ArgumentNullException(nameof(capabilityStore));
        WorkerStore     = workerStore ?? throw new ArgumentNullException(nameof(workerStore));
        TaskStore       = taskStore ?? throw new ArgumentNullException(nameof(taskStore));

        ConnectionStore.SnapshotChanged += OnConnectionSnapshotChanged;
        TaskStore.SnapshotChanged       += OnTaskSnapshotChanged;
    }

    /// <summary>独立连接状态仓库。</summary>
    public ConnectionStateStore ConnectionStore { get; }

    /// <summary>独立能力状态仓库。</summary>
    public CapabilityStateStore CapabilityStore { get; }

    /// <summary>独立 Worker 状态仓库。</summary>
    public WorkerStateStore WorkerStore { get; }

    /// <summary>独立任务状态仓库。</summary>
    public TaskStateStore TaskStore { get; }

    /// <summary>状态提交后发布兼容旧界面的不可变快照。</summary>
    public event EventHandler<AppSnapshot>? SnapshotChanged;

    /// <summary>当前兼容快照。</summary>
    public AppSnapshot Snapshot => CreateAppSnapshot(
        ConnectionStore.Snapshot,
        TaskStore.Snapshot);

    /// <summary>当前 Control Center 完整组合快照。</summary>
    public ControlCenterSnapshot ControlCenterSnapshot => new(
        ConnectionStore.Snapshot,
        CapabilityStore.Snapshot,
        WorkerStore.Snapshot,
        TaskStore.Snapshot);

    /// <summary>用 REST 初始数据替换任务集合，并通知旧界面执行完整归并。</summary>
    public void ReplaceTasks(IEnumerable<TaskRecord> tasks) =>
        TaskStore.ReplaceTasks(tasks);

    /// <summary>归并一个 REST 返回任务。</summary>
    public void UpsertTask(TaskRecord task) =>
        TaskStore.UpsertTask(task);

    /// <summary>归并连续事件；重复或序号跳跃均返回 false。</summary>
    public bool Apply(
        EventEnvelope envelope,
        Predicate<TaskRecord>? includeTask = null) =>
        TaskStore.Apply(envelope, includeTask) == SequenceApplyResult.Applied;

    /// <summary>更新连接状态和可选错误摘要。</summary>
    public void SetConnection(ConnectionState state, string? error = null) =>
        ConnectionStore.Set(state, error);

    private void OnConnectionSnapshotChanged(
        object? sender,
        ConnectionSnapshot connection)
    {
        var snapshot = CreateAppSnapshot(connection, TaskStore.Snapshot);
        PublishSnapshot(snapshot);
    }

    private void OnTaskSnapshotChanged(
        object? sender,
        TaskStateSnapshot tasks)
    {
        var snapshot = CreateAppSnapshot(ConnectionStore.Snapshot, tasks);
        PublishSnapshot(snapshot);
    }

    private static AppSnapshot CreateAppSnapshot(
        ConnectionSnapshot connection,
        TaskStateSnapshot tasks) => new(
            connection.State,
            tasks.Tasks,
            connection.LastError,
            tasks.LastSequence,
            tasks.TaskReset,
            tasks.ChangedTask);

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
