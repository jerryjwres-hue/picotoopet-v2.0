using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
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
    private const string DiagnosticTaskType = "system.diagnostic_snapshot";

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
    private readonly IReadOnlyList<TaskCenterFilterOption> _filterOptions = DefaultFilters;
    private IReadOnlyList<TaskRowViewModel> _allTasks = Array.Empty<TaskRowViewModel>();
    private IReadOnlyList<TaskRowViewModel> _visibleTasks = Array.Empty<TaskRowViewModel>();
    private TaskCenterFilter _selectedFilter;
    private TaskRowViewModel? _selectedTask;
    private WorkerSnapshot _worker = WorkerSnapshot.NotDeployed;
    private string _workerStatusText = "执行器未部署";
    private string _workerReasonText = "Queued 任务不会自动执行。";
    private string _statusMessage = "任务列表来自 Mac Core 耐久队列。";
    private bool _isBusy;
    private DiagnosticResultViewModel? _diagnosticResult;
    private bool _isDiagnosticResultVisible;
    private bool _isRefreshingVisibleTasks;
    private Task? _observationTask;

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

    public IReadOnlyList<TaskCenterFilterOption> FilterOptions => _filterOptions;

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
            var previousTaskId = _selectedTask?.TaskId;
            if (SetProperty(ref _selectedTask, value))
            {
                var currentTaskId = value?.TaskId;
                if (!_isRefreshingVisibleTasks
                    && !string.Equals(
                        previousTaskId,
                        currentTaskId,
                        StringComparison.Ordinal))
                {
                    ClearDiagnosticResult();
                }
                RaiseActionProperties();
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
                RaiseActionProperties();
            }
        }
    }

    public DiagnosticResultViewModel? DiagnosticResult
    {
        get => _diagnosticResult;
        private set => SetProperty(ref _diagnosticResult, value);
    }

    public bool IsDiagnosticResultVisible
    {
        get => _isDiagnosticResultVisible;
        private set => SetProperty(ref _isDiagnosticResultVisible, value);
    }

    public bool CanCancelSelected =>
        !IsBusy && SelectedTask?.CanCancel == true;

    public bool CanRetrySelected =>
        !IsBusy && SelectedTask?.CanRetry == true;

    public bool CanViewDiagnosticResult =>
        !IsBusy && SelectedTask?.CanViewDiagnosticResult == true;

    public bool CanCreateDiagnostic =>
        !IsBusy
        && (_observationTask is null || _observationTask.IsCompleted)
        && _worker.Available
        && _worker.SupportedTaskTypes.Contains(
            DiagnosticTaskType,
            StringComparer.Ordinal)
        && !AllTasks.Any(IsActiveDiagnostic);

    public string DiagnosticCreateReason
    {
        get
        {
            if (IsBusy)
            {
                return "正在处理任务操作。";
            }
            if (_observationTask is { IsCompleted: false })
            {
                return "正在观察刚创建的系统诊断任务。";
            }
            if (!_worker.Available)
            {
                return "Mac Worker 当前不可用。";
            }
            if (!_worker.SupportedTaskTypes.Contains(
                    DiagnosticTaskType,
                    StringComparer.Ordinal))
            {
                return "当前 Worker 尚不支持系统诊断快照。";
            }
            if (AllTasks.Any(IsActiveDiagnostic))
            {
                return "已有活动系统诊断任务，请等待其进入终态。";
            }
            return "创建一份不含路径、日志正文、Token 或网络信息的本地诊断快照。";
        }
    }

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

    /// <summary>使用固定合同创建诊断任务，单次可重试网络故障复用同一幂等键。</summary>
    public async Task CreateDiagnosticAsync(CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能执行任务动作。");
        if (!CanCreateDiagnostic)
        {
            throw new InvalidOperationException(DiagnosticCreateReason);
        }

        var idempotencyKey = $"windows-diagnostic-{Guid.NewGuid():N}";
        IsBusy = true;
        StatusMessage = "正在创建系统诊断快照……";
        TaskRecord created;
        try
        {
            try
            {
                created = await session.CreateDiagnosticSnapshotAsync(
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            catch (ApiException exception) when (exception.Retryable)
            {
                StatusMessage = "网络暂时不可用，正在使用同一幂等键重试一次……";
                created = await session.CreateDiagnosticSnapshotAsync(
                    idempotencyKey,
                    cancellationToken).ConfigureAwait(true);
            }
            StatusMessage = $"诊断任务 {created.TaskId} 已入队。";
        }
        catch (Exception)
        {
            StatusMessage = "创建诊断任务失败；详细信息已写入脱敏日志。";
            throw;
        }
        finally
        {
            IsBusy = false;
        }

        _observationTask = ObserveCreatedTaskAsync(created.TaskId, cancellationToken);
        RaiseActionProperties();
    }

    /// <summary>加载当前已完成诊断任务的固定卡片。</summary>
    public async Task LoadSelectedDiagnosticResultAsync(CancellationToken cancellationToken)
    {
        var session = _session
            ?? throw new InvalidOperationException("Smoke test 模式不能执行任务动作。");
        var selected = SelectedTask
            ?? throw new InvalidOperationException("请先选择任务。");
        if (!selected.CanViewDiagnosticResult)
        {
            throw new InvalidOperationException("当前任务没有可读取的诊断结果。");
        }

        IsBusy = true;
        StatusMessage = $"正在读取诊断结果 {selected.TaskId}……";
        try
        {
            var result = await session.GetDiagnosticResultAsync(
                selected.TaskId,
                cancellationToken).ConfigureAwait(true);
            DiagnosticResult = DiagnosticResultViewModel.FromResult(result);
            IsDiagnosticResultVisible = true;
            StatusMessage = "诊断结果已加载并通过固定合同校验。";
        }
        catch (Exception)
        {
            DiagnosticResult = DiagnosticResultViewModel.FromError(
                "诊断结果无法安全显示；详细信息已写入脱敏日志。");
            IsDiagnosticResultVisible = true;
            StatusMessage = "读取诊断结果失败；详细信息已写入脱敏日志。";
            throw;
        }
        finally
        {
            IsBusy = false;
        }
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
            var task = await session.CancelTaskAsync(selected.TaskId, cancellationToken)
                .ConfigureAwait(true);
            StatusMessage = task.Status == "Running"
                ? "取消意图已提交，Worker 正在安全停止子进程。"
                : "取消请求已由 Mac Core 完成。";
        }
        catch (Exception)
        {
            StatusMessage = "取消失败；详细信息已写入脱敏日志。";
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
            StatusMessage = selected.IsDiagnostic
                && !string.Equals(
                    retried.ParentTaskId,
                    selected.TaskId,
                    StringComparison.Ordinal)
                ? $"已有活动诊断任务 {retried.TaskId}，未重复创建。"
                : $"已创建重试子任务 {retried.TaskId}。";
        }
        catch (Exception)
        {
            StatusMessage = "重试失败；详细信息已写入脱敏日志。";
            throw;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task ObserveCreatedTaskAsync(
        string taskId,
        CancellationToken cancellationToken)
    {
        var session = _session;
        if (session is null)
        {
            return;
        }
        try
        {
            var observation = await session.ObserveTaskAsync(taskId, cancellationToken)
                .ConfigureAwait(true);
            StatusMessage = observation.ObservationWindowExpired
                ? "诊断任务仍在后台运行；任务中心将继续接收事件更新。"
                : observation.Task.Status switch
                {
                    "Completed" => "诊断任务已完成，可以查看固定结果卡片。",
                    "Cancelled" => "诊断任务已安全取消。",
                    "Failed"    => "诊断任务受控失败，请查看错误码或创建重试任务。",
                    _           => $"诊断任务状态：{observation.Task.Status}",
                };
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            StatusMessage = "诊断任务观察已取消；任务仍由 Mac Core 管理。";
        }
        catch (Exception)
        {
            StatusMessage = "诊断任务观察暂时中断；任务仍由 Mac Core 管理。";
        }
        finally
        {
            _observationTask = null;
            RaiseActionProperties();
        }
    }

    private void ApplySnapshot(
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        ArgumentNullException.ThrowIfNull(worker);
        var selectedId = SelectedTask?.TaskId;
        _worker = worker;
        AllTasks = tasks
            .OrderByDescending(task => task.UpdatedAt)
            .Select(task => TaskRowViewModel.FromRecord(task, worker))
            .ToArray();
        WorkerStatusText = FormatWorkerStatus(worker);
        WorkerReasonText = FormatWorkerReason(worker);
        ApplyFilter(selectedId);
        RaiseActionProperties();
    }

    private void ApplyFilter()
    {
        ApplyFilter(SelectedTask?.TaskId);
    }

    /// <summary>刷新 WPF ItemsSource 时按 task_id 保留逻辑选择，避免对象替换清空诊断卡。</summary>
    private void ApplyFilter(string? selectedId)
    {
        var diagnosticTaskId = IsDiagnosticResultVisible && DiagnosticResult is not null
            ? selectedId
            : null;
        _isRefreshingVisibleTasks = true;
        try
        {
            VisibleTasks = AllTasks.Where(MatchesFilter).ToArray();
            SelectedTask = ResolveSelection(VisibleTasks, selectedId);
        }
        finally
        {
            _isRefreshingVisibleTasks = false;
        }

        if (!string.IsNullOrWhiteSpace(diagnosticTaskId)
            && !string.Equals(
                SelectedTask?.TaskId,
                diagnosticTaskId,
                StringComparison.Ordinal))
        {
            ClearDiagnosticResult();
        }
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

    /// <summary>仅在逻辑选择真正离开当前诊断任务时清空卡片。</summary>
    private void ClearDiagnosticResult()
    {
        DiagnosticResult = null;
        IsDiagnosticResultVisible = false;
    }

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanCancelSelected));
        RaisePropertyChanged(nameof(CanRetrySelected));
        RaisePropertyChanged(nameof(CanViewDiagnosticResult));
        RaisePropertyChanged(nameof(CanCreateDiagnostic));
        RaisePropertyChanged(nameof(DiagnosticCreateReason));
    }

    private static bool IsActiveDiagnostic(TaskRowViewModel task) =>
        task.IsDiagnostic
        && task.Status is (
            "Created" or
            "Validating" or
            "Queued" or
            "Running" or
            "WaitingForTool" or
            "WaitingForApproval" or
            "Retrying");

    private static TaskRowViewModel? ResolveSelection(
        IReadOnlyList<TaskRowViewModel> tasks,
        string? selectedId)
    {
        if (!string.IsNullOrWhiteSpace(selectedId))
        {
            for (var index = 0; index < tasks.Count; index++)
            {
                if (string.Equals(tasks[index].TaskId, selectedId, StringComparison.Ordinal))
                {
                    return tasks[index];
                }
            }
        }
        return tasks.Count == 0 ? null : tasks[0];
    }

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