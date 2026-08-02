using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>任务中心支持的互斥只读筛选。</summary>
public enum TaskCenterFilter
{
    All,
    Active,
    WaitingForWorker,
    Completed,
    FailedOrCancelled,
}

/// <summary>供 WPF ComboBox 显示的筛选项。</summary>
public sealed record TaskCenterFilterOption(
    TaskCenterFilter Value,
    string Label);

/// <summary>展示真实耐久队列、Worker 状态和安全任务动作。</summary>
public sealed class TaskCenterPageViewModel : PageViewModel
{
    private static readonly IReadOnlyList<TaskCenterFilterOption> DefaultFilters =
        new TaskCenterFilterOption[]
        {
            new(TaskCenterFilter.All, "全部"),
            new(TaskCenterFilter.Active, "活动任务"),
            new(TaskCenterFilter.WaitingForWorker, "等待执行器"),
            new(TaskCenterFilter.Completed, "已完成"),
            new(TaskCenterFilter.FailedOrCancelled, "失败或已取消"),
        };

    private readonly ControlCenterSession? _session;
    private IReadOnlyList<TaskRowViewModel> _allTasks = Array.Empty<TaskRowViewModel>();
    private IReadOnlyList<TaskRowViewModel> _visibleTasks = Array.Empty<TaskRowViewModel>();
    private TaskCenterFilter _selectedFilter;
    private TaskRowViewModel? _selectedTask;
    private string _workerStatusText = "执行器未部署";
    private string _workerReasonText = "Queued 任务不会自动执行。";
    private string _statusMessage = "任务列表来自 Mac Core 耐久队列。";
    private bool _isBusy;

    /// <summary>创建绑定真实 Session 的任务中心。</summary>
    public TaskCenterPageViewModel(
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
        : base("任务中心")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        ArgumentNullException.ThrowIfNull(snapshot);
        UpdateSnapshot(snapshot);
    }

    private TaskCenterPageViewModel(
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker)
        : base("任务中心")
    {
        ApplySnapshot(tasks, worker);
    }

    public IReadOnlyList<TaskCenterFilterOption> FilterOptions => DefaultFilters;

    public IReadOnlyList<TaskRowViewModel> AllTasks
    {
        get => _allTasks;
        private set => SetProperty(ref _allTasks, value);
    }

    public IReadOnlyList<TaskRowViewModel> VisibleTasks
    {
        get => _visibleTasks;
        private set => SetProperty(ref _visibleTasks, value);
    }

    public TaskCenterFilter SelectedFilter
    {
        get => _selectedFilter;
        set
        {
            if (SetProperty(ref _selectedFilter, value))
            {
                ApplyFilter();
            }
        }
    }

    public TaskRowViewModel? SelectedTask
    {
        get => _selectedTask;
        set
        {
            if (SetProperty(ref _selectedTask, value))
            {
                RaisePropertyChanged(nameof(CanCancelSelected));
                RaisePropertyChanged(nameof(CanRetrySelected));
            }
        }
    }

    public string WorkerStatusText
    {
        get => _workerStatusText;
        private set => SetProperty(ref _workerStatusText, value);
    }

    public string WorkerReasonText
    {
        get => _workerReasonText;
        private set => SetProperty(ref _workerReasonText, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanCancelSelected));
                RaisePropertyChanged(nameof(CanRetrySelected));
            }
        }
    }

    public bool CanCancelSelected =>
        !IsBusy && SelectedTask?.CanCancel == true;

    public bool CanRetrySelected =>
        !IsBusy && SelectedTask?.CanRetry == true;

    /// <summary>创建不依赖网络的确定性任务中心模型。</summary>
    public static TaskCenterPageViewModel CreateForSmokeTest(
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker) => new(tasks, worker);

    /// <summary>保留筛选和选中任务，并应用最新 Session 快照。</summary>
    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ApplySnapshot(snapshot.State.Tasks.Tasks, snapshot.State.Worker);
    }

    /// <summary>取消当前可取消任务；服务端状态机仍是最终裁决者。</summary>
    public async Task CancelSelectedAsync(CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能执行任务动作。");
        var selected = SelectedTask
            ?? throw new InvalidOperationException("请先选择任务。");
        if (!selected.CanCancel)
        {
            throw new InvalidOperationException("当前任务状态不允许取消。");
        }

        IsBusy = true;
        StatusMessage = $"正在取消任务 {selected.TaskId}……";
        try
        {
            await session.CancelTaskAsync(selected.TaskId, cancellationToken).ConfigureAwait(true);
            StatusMessage = "取消请求已由 Mac Core 接受。";
        }
        catch (Exception exception)
        {
            StatusMessage = $"取消失败：{exception.Message}";
            throw;
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>为 Failed 或 Cancelled 任务创建新的子任务，不重新打开原任务。</summary>
    public async Task RetrySelectedAsync(CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能执行任务动作。");
        var selected = SelectedTask
            ?? throw new InvalidOperationException("请先选择任务。");
        if (!selected.CanRetry)
        {
            throw new InvalidOperationException("只有 Failed 或 Cancelled 任务可以重试。");
        }

        IsBusy = true;
        StatusMessage = $"正在为任务 {selected.TaskId} 创建重试子任务……";
        try
        {
            var retried = await session.RetryTaskAsync(selected.TaskId, cancellationToken)
                .ConfigureAwait(true);
            StatusMessage = $"已创建重试子任务 {retried.TaskId}。";
        }
        catch (Exception exception)
        {
            StatusMessage = $"重试失败：{exception.Message}";
            throw;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void ApplySnapshot(
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        ArgumentNullException.ThrowIfNull(worker);
        var selectedId = SelectedTask?.TaskId;
        AllTasks = tasks
            .OrderByDescending(task => task.UpdatedAt)
            .Select(task => TaskRowViewModel.FromRecord(task, worker))
            .ToArray();
        WorkerStatusText = FormatWorkerStatus(worker);
        WorkerReasonText = FormatWorkerReason(worker);
        ApplyFilter();
        SelectedTask = selectedId is null
            ? VisibleTasks.FirstOrDefault()
            : VisibleTasks.FirstOrDefault(task =>
                string.Equals(task.TaskId, selectedId, StringComparison.Ordinal))
                ?? VisibleTasks.FirstOrDefault();
    }

    private void ApplyFilter()
    {
        var selectedId = SelectedTask?.TaskId;
        VisibleTasks = AllTasks.Where(MatchesFilter).ToArray();
        SelectedTask = selectedId is null
            ? VisibleTasks.FirstOrDefault()
            : VisibleTasks.FirstOrDefault(task =>
                string.Equals(task.TaskId, selectedId, StringComparison.Ordinal))
                ?? VisibleTasks.FirstOrDefault();
    }

    private bool MatchesFilter(TaskRowViewModel task) => SelectedFilter switch
    {
        TaskCenterFilter.All => true,
        TaskCenterFilter.Active => task.Status is
            "Created" or
            "Validating" or
            "Running" or
            "WaitingForTool" or
            "WaitingForApproval" or
            "Retrying" ||
            (task.Status == "Queued" && !task.IsWaitingForWorker),
        TaskCenterFilter.WaitingForWorker => task.IsWaitingForWorker,
        TaskCenterFilter.Completed => task.Status is "Completed" or "Archived",
        TaskCenterFilter.FailedOrCancelled => task.Status is "Failed" or "Cancelled",
        _ => false,
    };

    private static string FormatWorkerStatus(WorkerSnapshot worker)
    {
        if (worker.Available)
        {
            return string.IsNullOrWhiteSpace(worker.WorkerId)
                ? "执行器在线"
                : $"执行器在线 · {worker.WorkerId}";
        }
        return worker.State switch
        {
            "starting"     => "执行器启动中",
            "degraded"     => "执行器降级",
            "offline"      => "执行器离线",
            "not_deployed" => "执行器未部署",
            _              => "执行器不可用",
        };
    }

    private static string FormatWorkerReason(WorkerSnapshot worker) => worker.Reason switch
    {
        "worker_runtime_not_installed" => "Mac 尚未安装任务执行器；Queued 任务不会自动执行。",
        _ when string.IsNullOrWhiteSpace(worker.Reason) => "服务端未提供执行器原因。",
        _ => worker.Reason,
    };
}
