using System.ComponentModel;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

public enum OperatorTaskListMode
{
    InProgress,
    Completed,
    Deleted,
}

/// <summary>任务卡片的临时选择状态；不会写入 Mac Core。</summary>
public sealed class OperatorTaskListItem : ObservableObject
{
    private bool _isSelected;

    public OperatorTaskListItem(OperatorTaskCard card, bool isSelected = false)
    {
        Card = card;
        _isSelected = isSelected;
    }

    public OperatorTaskCard Card { get; }
    public string TaskId => Card.TaskId;
    public string Title => Card.Title;
    public string StageText => Card.StageText;
    public string StatusText => Card.StatusText;
    public string UpdatedAtText => Card.UpdatedAtText;
    public string? ErrorText => Card.ErrorText;
    public bool HasResult => Card.HasResult;

    public bool IsSelected
    {
        get => _isSelected;
        set => SetProperty(ref _isSelected, value);
    }
}

/// <summary>简单模式进行中/已完成/已删除共用列表，并把写操作交给 Mac Core。</summary>
public sealed class OperatorTaskListPageViewModel : PageViewModel
{
    private readonly OperatorTaskListMode _mode;
    private readonly ControlCenterSession? _session;
    private ControlCenterSessionSnapshot _snapshot;
    private IReadOnlyList<OperatorTaskListItem> _items = Array.Empty<OperatorTaskListItem>();
    private string _emptyMessage = string.Empty;
    private string _actionMessage = string.Empty;
    private bool _isBusy;

    /// <summary>运行时构造函数。</summary>
    public OperatorTaskListPageViewModel(
        string title,
        OperatorTaskListMode mode,
        ControlCenterSession session,
        ControlCenterSessionSnapshot snapshot)
        : base(title)
    {
        _mode = mode;
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _snapshot = snapshot ?? throw new ArgumentNullException(nameof(snapshot));
        UpdateSnapshot(snapshot);
    }

    /// <summary>保留旧 smoke 构造面；只读，不执行 Core 写操作。</summary>
    public OperatorTaskListPageViewModel(
        string title,
        bool completed,
        ControlCenterSessionSnapshot snapshot)
        : base(title)
    {
        _mode = completed ? OperatorTaskListMode.Completed : OperatorTaskListMode.InProgress;
        _snapshot = snapshot ?? throw new ArgumentNullException(nameof(snapshot));
        UpdateSnapshot(snapshot);
    }

    public IReadOnlyList<OperatorTaskListItem> Items
    {
        get => _items;
        private set => SetProperty(ref _items, value);
    }

    public string EmptyMessage
    {
        get => _emptyMessage;
        private set => SetProperty(ref _emptyMessage, value);
    }

    public string ActionMessage
    {
        get => _actionMessage;
        private set => SetProperty(ref _actionMessage, value);
    }

    public bool IsDeletedMode => _mode == OperatorTaskListMode.Deleted;
    public string BulkActionText => IsDeletedMode ? "恢复所选" : "删除所选";
    public string SingleActionText => IsDeletedMode ? "恢复" : "删除";
    public int SelectedCount => Items.Count(item => item.IsSelected);
    public bool HasSelection => SelectedCount > 0;

    public bool IsBusy
    {
        get => _isBusy;
        private set => SetProperty(ref _isBusy, value);
    }

    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        _snapshot = snapshot;
        var selected = Items.Where(item => item.IsSelected)
            .Select(item => item.TaskId)
            .ToHashSet(StringComparer.Ordinal);
        var projection = OperatorProjection.FromSnapshot(snapshot);
        var cards = _mode switch
        {
            OperatorTaskListMode.Completed => projection.Completed,
            OperatorTaskListMode.Deleted => projection.Deleted,
            _ => projection.InProgress,
        };
        foreach (var oldItem in Items)
        {
            oldItem.PropertyChanged -= OnItemPropertyChanged;
        }
        var items = cards
            .Select(card => new OperatorTaskListItem(card, selected.Contains(card.TaskId)))
            .ToArray();
        foreach (var item in items)
        {
            item.PropertyChanged += OnItemPropertyChanged;
        }
        Items = items;
        EmptyMessage = Items.Count == 0
            ? _mode switch
            {
                OperatorTaskListMode.Completed => "还没有已结束的任务。",
                OperatorTaskListMode.Deleted => "已删除里没有任务。",
                _ => "现在没有正在处理的任务。",
            }
            : string.Empty;
        RaiseSelectionProperties();
    }

    public void SelectAllVisible(bool selected)
    {
        foreach (var item in Items)
        {
            item.IsSelected = selected;
        }
        RaiseSelectionProperties();
    }

    public async Task ApplySelectedActionAsync(CancellationToken cancellationToken = default)
    {
        var taskIds = Items.Where(item => item.IsSelected)
            .Select(item => item.TaskId)
            .ToArray();
        if (taskIds.Length == 0)
        {
            ActionMessage = "请先选择任务。";
            return;
        }
        await ApplyActionAsync(taskIds, cancellationToken).ConfigureAwait(true);
    }

    public Task ApplySingleActionAsync(
        string taskId,
        CancellationToken cancellationToken = default) =>
        ApplyActionAsync([taskId], cancellationToken);

    public TaskDetailViewModel CreateDetail(string taskId)
    {
        if (_session is null)
        {
            throw new InvalidOperationException("Smoke 模式不能读取真实任务详情。");
        }
        var task = _snapshot.State.Tasks.Tasks.FirstOrDefault(
            candidate => string.Equals(candidate.TaskId, taskId, StringComparison.Ordinal))
            ?? throw new KeyNotFoundException($"任务不存在：{taskId}");
        return new TaskDetailViewModel(_session, task);
    }

    private async Task ApplyActionAsync(
        IReadOnlyList<string> taskIds,
        CancellationToken cancellationToken)
    {
        if (_session is null)
        {
            ActionMessage = "当前页面没有连接 Mac Core。";
            return;
        }
        IsBusy = true;
        try
        {
            var response = IsDeletedMode
                ? await _session.RestoreTasksAsync(taskIds, cancellationToken).ConfigureAwait(true)
                : await _session.HideTasksAsync(taskIds, cancellationToken).ConfigureAwait(true);
            var failed = response.Outcomes.Count(outcome => !outcome.Success || outcome.PendingCancel);
            ActionMessage = failed == 0
                ? IsDeletedMode
                    ? $"已恢复 {response.Outcomes.Count} 个任务。"
                    : $"已将 {response.Outcomes.Count} 个任务移入已删除。"
                : $"已处理 {response.Outcomes.Count} 个任务，其中 {failed} 个仍需等待或重试。";
        }
        catch (Exception exception)
        {
            ActionMessage = exception.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(OperatorTaskListItem.IsSelected))
        {
            RaiseSelectionProperties();
        }
    }

    private void RaiseSelectionProperties()
    {
        RaisePropertyChanged(nameof(SelectedCount));
        RaisePropertyChanged(nameof(HasSelection));
    }
}
