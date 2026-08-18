using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>任务列表使用的可增量更新行模型，并将 Worker 可用性解释为真实用户状态。</summary>
public sealed class TaskRowViewModel : ObservableObject
{
    private const string DiagnosticTaskType = "system.diagnostic_snapshot";

    private string _taskType;
    private string _status;
    private string _displayStatus;
    private DateTimeOffset _createdAt;
    private DateTimeOffset _updatedAt;
    private string _safeErrorSummary;
    private string? _errorCode;
    private string _attemptText;
    private bool _isWaitingForWorker;
    private bool _canCancel;
    private bool _canRetry;
    private int _priority;
    private int _timeoutSeconds;
    private string? _projectId;
    private string? _resultId;

    private TaskRowViewModel(TaskRecord task, WorkerSnapshot worker)
    {
        TaskId          = task.TaskId;
        _taskType       = task.TaskType;
        _status         = task.Status;
        _displayStatus  = FormatStatus(task.Status, worker);
        _createdAt      = task.CreatedAt;
        _updatedAt      = task.UpdatedAt;
        _safeErrorSummary = FormatSafeErrorSummary(task.Status, task.ErrorCode);
        _errorCode      = task.ErrorCode;
        _attemptText    = FormatAttempt(task);
        _isWaitingForWorker = IsWaiting(task.Status, worker);
        _canCancel      = CanCancelStatus(task.TaskType, task.Status);
        _canRetry       = CanRetryStatus(task.Status);
        _priority       = task.Priority;
        _timeoutSeconds = task.TimeoutSeconds;
        _projectId      = task.ProjectId;
        _resultId       = task.ResultId;
    }

    public string TaskId { get; }

    public string TaskType
    {
        get => _taskType;
        private set => SetProperty(ref _taskType, value);
    }

    /// <summary>服务端原始任务状态，不被客户端改写。</summary>
    public string Status
    {
        get => _status;
        private set => SetProperty(ref _status, value);
    }

    /// <summary>结合 Worker 可用性形成的真实用户状态。</summary>
    public string DisplayStatus
    {
        get => _displayStatus;
        private set => SetProperty(ref _displayStatus, value);
    }

    public DateTimeOffset CreatedAt
    {
        get => _createdAt;
        private set => SetProperty(ref _createdAt, value);
    }

    public DateTimeOffset UpdatedAt
    {
        get => _updatedAt;
        private set => SetProperty(ref _updatedAt, value);
    }

    /// <summary>只展示稳定状态和错误码，不把 Core 原始错误正文带入界面。</summary>
    public string SafeErrorSummary
    {
        get => _safeErrorSummary;
        private set => SetProperty(ref _safeErrorSummary, value);
    }

    public string? ErrorCode
    {
        get => _errorCode;
        private set => SetProperty(ref _errorCode, value);
    }

    public string AttemptText
    {
        get => _attemptText;
        private set => SetProperty(ref _attemptText, value);
    }

    public bool IsWaitingForWorker
    {
        get => _isWaitingForWorker;
        private set => SetProperty(ref _isWaitingForWorker, value);
    }

    public bool CanCancel
    {
        get => _canCancel;
        private set => SetProperty(ref _canCancel, value);
    }

    public bool CanRetry
    {
        get => _canRetry;
        private set => SetProperty(ref _canRetry, value);
    }

    public int Priority
    {
        get => _priority;
        private set => SetProperty(ref _priority, value);
    }

    public int TimeoutSeconds
    {
        get => _timeoutSeconds;
        private set => SetProperty(ref _timeoutSeconds, value);
    }

    public string? ProjectId
    {
        get => _projectId;
        private set => SetProperty(ref _projectId, value);
    }

    public string? ResultId
    {
        get => _resultId;
        private set => SetProperty(ref _resultId, value);
    }

    public bool IsDiagnostic => string.Equals(
        TaskType,
        DiagnosticTaskType,
        StringComparison.Ordinal);

    public bool CanViewDiagnosticResult =>
        IsDiagnostic
        && string.Equals(Status, "Completed", StringComparison.Ordinal)
        && !string.IsNullOrWhiteSpace(ResultId);

    /// <summary>保留旧总览调用面；未知 Worker 一律视为未部署。</summary>
    public static TaskRowViewModel FromRecord(TaskRecord task) =>
        new(task, WorkerSnapshot.NotDeployed);

    /// <summary>从领域任务和 Worker 快照创建任务中心行。</summary>
    public static TaskRowViewModel FromRecord(
        TaskRecord task,
        WorkerSnapshot worker) => new(task, worker);

    /// <summary>保留旧增量更新调用面；未知 Worker 一律视为未部署。</summary>
    public void UpdateFrom(TaskRecord task) =>
        UpdateFrom(task, WorkerSnapshot.NotDeployed);

    /// <summary>只更新真正变化的字段，降低 UI Dispatcher 和绑定通知开销。</summary>
    public void UpdateFrom(TaskRecord task, WorkerSnapshot worker)
    {
        if (!string.Equals(TaskId, task.TaskId, StringComparison.Ordinal))
        {
            throw new ArgumentException("不能使用其他任务的数据更新当前行。", nameof(task));
        }
        TaskType           = task.TaskType;
        Status             = task.Status;
        DisplayStatus      = FormatStatus(task.Status, worker);
        CreatedAt          = task.CreatedAt;
        UpdatedAt          = task.UpdatedAt;
        SafeErrorSummary   = FormatSafeErrorSummary(task.Status, task.ErrorCode);
        ErrorCode          = task.ErrorCode;
        AttemptText        = FormatAttempt(task);
        IsWaitingForWorker = IsWaiting(task.Status, worker);
        CanCancel          = CanCancelStatus(task.TaskType, task.Status);
        CanRetry           = CanRetryStatus(task.Status);
        Priority           = task.Priority;
        TimeoutSeconds     = task.TimeoutSeconds;
        ProjectId          = task.ProjectId;
        ResultId           = task.ResultId;
        RaisePropertyChanged(nameof(IsDiagnostic));
        RaisePropertyChanged(nameof(CanViewDiagnosticResult));
    }

    private static bool IsWaiting(string status, WorkerSnapshot worker) =>
        string.Equals(status, "Queued", StringComparison.Ordinal)
        && !worker.Available;

    private static bool CanCancelStatus(string taskType, string status)
    {
        if (string.Equals(taskType, DiagnosticTaskType, StringComparison.Ordinal))
        {
            return status is "Queued" or "Running";
        }

        return status is
            "Created" or
            "Validating" or
            "Queued" or
            "Running" or
            "WaitingForTool" or
            "WaitingForApproval" or
            "Retrying";
    }

    private static bool CanRetryStatus(string status) => status is
        "Failed" or
        "Cancelled";

    private static string FormatAttempt(TaskRecord task) =>
        $"{task.AttemptCount}/{task.MaxAttempts}";

    private static string FormatSafeErrorSummary(string status, string? errorCode)
    {
        if (status == "Failed")
        {
            return string.IsNullOrWhiteSpace(errorCode)
                ? "任务执行失败；详细信息已记录，可创建重试任务。"
                : $"任务执行失败（错误码：{errorCode}）；详细信息已记录，可创建重试任务。";
        }

        return status == "Cancelled"
            ? "任务已取消。"
            : "无";
    }

    private static string FormatStatus(string status, WorkerSnapshot worker) => status switch
    {
        "Created"            => "已创建",
        "Validating"         => "校验中",
        "Queued" when !worker.Available => "等待执行器",
        "Queued"             => "排队中",
        "Running"            => "运行中",
        "WaitingForTool"     => "等待工具",
        "WaitingForApproval" => "等待审批",
        "Retrying"           => "正在重试",
        "Completed"          => "已完成",
        "Failed"             => "失败",
        "Cancelled"          => "已取消",
        "Archived"           => "已归档",
        _                     => status,
    };
}
