using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>任务列表使用的可增量更新行模型，避免每条事件重建整张视觉树。</summary>
public sealed class TaskRowViewModel : ObservableObject
{
    private string _taskType;
    private string _status;
    private DateTimeOffset _updatedAt;
    private string? _error;

    private TaskRowViewModel(TaskRecord task)
    {
        TaskId    = task.TaskId;
        _taskType = task.TaskType;
        _status   = task.Status;
        _updatedAt = task.UpdatedAt;
        _error    = task.ErrorMessage;
    }

    public string TaskId { get; }

    public string TaskType
    {
        get => _taskType;
        private set => SetProperty(ref _taskType, value);
    }

    public string Status
    {
        get => _status;
        private set => SetProperty(ref _status, value);
    }

    public DateTimeOffset UpdatedAt
    {
        get => _updatedAt;
        private set => SetProperty(ref _updatedAt, value);
    }

    public string? Error
    {
        get => _error;
        private set => SetProperty(ref _error, value);
    }

    /// <summary>从领域任务快照创建界面行。</summary>
    public static TaskRowViewModel FromRecord(TaskRecord task) => new(task);

    /// <summary>只更新真正变化的字段，降低 UI Dispatcher 和绑定通知开销。</summary>
    public void UpdateFrom(TaskRecord task)
    {
        if (!string.Equals(TaskId, task.TaskId, StringComparison.Ordinal))
        {
            throw new ArgumentException("不能使用其他任务的数据更新当前行。", nameof(task));
        }
        TaskType = task.TaskType;
        Status    = task.Status;
        UpdatedAt = task.UpdatedAt;
        Error     = task.ErrorMessage;
    }
}
