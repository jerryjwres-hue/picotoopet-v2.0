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
    public string CategoryText => Card.CategoryText;
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

/// <summary>简单模式进行中/已完成/已删除共用列表，并把任务写操作交给 Mac Core。</summary>
public sealed class OperatorTaskListPageViewModel : PageViewModel
{
    private const string AllCategories = "全部";

    private readonly OperatorTaskListMode _mode;
    private readonly ControlCenterSession? _session;
    private ControlCenterSessionSnapshot _snapshot;
    private IReadOnlyList<OperatorTaskCard> _allCards = Array.Empty<OperatorTaskCard>();
    private IReadOnlyList<OperatorTaskListItem> _items = Array.Empty<OperatorTaskListItem>();
    private IReadOnlyList<string> _categories = [AllCategories];
    private string _keyword = string.Empty;
    private string _selectedCategory = AllCategories;
    private DateTime? _startDate;
    private DateTime? _endDate;
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

    public IReadOnlyList<string> Categories
    {
        get => _categories;
        private set => SetProperty(ref _categories, value);
    }

    public string Keyword
    {
        get => _keyword;
        set => SetProperty(ref _keyword, value ?? string.Empty);
    }

    public string SelectedCategory
    {
        get => _selectedCategory;
        set => SetProperty(
            ref _selectedCategory,
            string.IsNullOrWhiteSpace(value) ? AllCategories : value);
    }

    public DateTime? StartDate
    {
        get => _startDate;
        set => SetProperty(ref _startDate, value);
    }

    public DateTime? EndDate
    {
        get => _endDate;
        set => SetProperty(ref _endDate, value);
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

    public bool IsInProgressMode => _mode == OperatorTaskListMode.InProgress;
    public bool IsCompletedMode => _mode == OperatorTaskListMode.Completed;
    public bool IsDeletedMode => _mode == OperatorTaskListMode.Deleted;

    public string BulkActionText => _mode switch
    {
        OperatorTaskListMode.InProgress => "取消所选",
        OperatorTaskListMode.Completed => "移到已删除",
        OperatorTaskListMode.Deleted => "恢复所选",
        _ => "执行",
    };

    public string SingleActionText => _mode switch
    {
        OperatorTaskListMode.InProgress => "取消任务",
        OperatorTaskListMode.Completed => "移到已删除",
        OperatorTaskListMode.Deleted => "恢复",
        _ => "执行",
    };

    public string ActionToolTip => _mode switch
    {
        OperatorTaskListMode.InProgress => "请求 Mac Core 安全取消任务；不会直接删除任务记录。",
        OperatorTaskListMode.Completed => "将已结束任务移入“已删除”；之后仍可恢复。",
        OperatorTaskListMode.Deleted => "把任务从“已删除”恢复到原有状态列表。",
        _ => "执行当前任务操作。",
    };

    public int SelectedCount => Items.Count(item => item.IsSelected);
    public bool HasSelection => SelectedCount > 0;
    public bool HasItems => Items.Count > 0;
    public bool CanSelectAll => HasItems && !IsBusy && SelectedCount < Items.Count;
    public bool CanClearSelection => HasSelection && !IsBusy;
    public bool CanApplySelection => HasSelection && !IsBusy;
    public bool CanApplyAnyAction => !IsBusy;

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

    /// <summary>刷新只读快照并保留仍可见任务的选择；筛选条件本身保持不变。</summary>
    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        _snapshot = snapshot;
        var selected = Items.Where(item => item.IsSelected)
            .Select(item => item.TaskId)
            .ToHashSet(StringComparer.Ordinal);
        var projection = OperatorProjection.FromSnapshot(snapshot);
        _allCards = _mode switch
        {
            OperatorTaskListMode.Completed => projection.Completed,
            OperatorTaskListMode.Deleted => projection.Deleted,
            _ => projection.InProgress,
        };

        Categories = new[] { AllCategories }
            .Concat(_allCards
                .Select(card => card.CategoryText)
                .Where(category => !string.IsNullOrWhiteSpace(category))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(category => category, StringComparer.CurrentCulture))
            .ToArray();
        if (!Categories.Contains(SelectedCategory, StringComparer.OrdinalIgnoreCase))
        {
            SelectedCategory = AllCategories;
        }

        RebuildVisibleItems(selected);
    }

    /// <summary>按当前关键词、分类和创建日期范围筛选一次本地快照。</summary>
    public void ApplyFilters()
    {
        if (StartDate.HasValue && EndDate.HasValue && StartDate.Value.Date > EndDate.Value.Date)
        {
            ActionMessage = "开始日期不能晚于结束日期。";
            return;
        }

        ActionMessage = string.Empty;
        RebuildVisibleItems();
    }

    /// <summary>清空所有筛选并恢复当前任务桶的完整列表。</summary>
    public void ClearFilters()
    {
        Keyword = string.Empty;
        SelectedCategory = AllCategories;
        StartDate = null;
        EndDate = null;
        ActionMessage = string.Empty;
        RebuildVisibleItems();
    }

    public void SelectAllVisible(bool selected)
    {
        if (IsBusy)
        {
            ActionMessage = "当前操作仍在处理中，请稍候。";
            return;
        }

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

    private void RebuildVisibleItems(IReadOnlySet<string>? selectedTaskIds = null)
    {
        var selected = selectedTaskIds
            ?? Items.Where(item => item.IsSelected)
                .Select(item => item.TaskId)
                .ToHashSet(StringComparer.Ordinal);
        foreach (var oldItem in Items)
        {
            oldItem.PropertyChanged -= OnItemPropertyChanged;
        }

        var cards = _allCards
            .Where(MatchesKeyword)
            .Where(MatchesCategory)
            .Where(MatchesDateRange)
            .ToArray();
        var items = cards
            .Select(card => new OperatorTaskListItem(card, selected.Contains(card.TaskId)))
            .ToArray();
        foreach (var item in items)
        {
            item.PropertyChanged += OnItemPropertyChanged;
        }
        Items = items;
        EmptyMessage = BuildEmptyMessage();
        RaiseSelectionProperties();
    }

    private bool MatchesKeyword(OperatorTaskCard card)
    {
        var keyword = Keyword.Trim();
        return keyword.Length == 0
            || card.SearchText.Contains(keyword, StringComparison.CurrentCultureIgnoreCase);
    }

    private bool MatchesCategory(OperatorTaskCard card) =>
        string.Equals(SelectedCategory, AllCategories, StringComparison.OrdinalIgnoreCase)
        || string.Equals(card.CategoryText, SelectedCategory, StringComparison.CurrentCultureIgnoreCase);

    private bool MatchesDateRange(OperatorTaskCard card)
    {
        var createdDate = card.CreatedAt.LocalDateTime.Date;
        if (StartDate.HasValue && createdDate < StartDate.Value.Date)
        {
            return false;
        }
        if (EndDate.HasValue && createdDate > EndDate.Value.Date)
        {
            return false;
        }
        return true;
    }

    private string BuildEmptyMessage()
    {
        if (_allCards.Count > 0 && Items.Count == 0)
        {
            return "没有符合当前筛选条件的任务。";
        }
        return _allCards.Count == 0
            ? _mode switch
            {
                OperatorTaskListMode.Completed => "还没有已结束的任务。",
                OperatorTaskListMode.Deleted => "已删除里没有任务。",
                _ => "现在没有正在处理的任务。",
            }
            : string.Empty;
    }

    private async Task ApplyActionAsync(
        string[] taskIds,
        CancellationToken cancellationToken)
    {
        if (_session is null)
        {
            ActionMessage = "当前页面没有连接 Mac Core。";
            return;
        }
        if (IsBusy)
        {
            ActionMessage = "当前操作仍在处理中，请稍候。";
            return;
        }

        IsBusy = true;
        ActionMessage = BuildBusyMessage(taskIds.Length);
        try
        {
            switch (_mode)
            {
                case OperatorTaskListMode.InProgress:
                    var cancelled = 0;
                    var failedToCancel = 0;
                    foreach (var taskId in taskIds)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        try
                        {
                            await _session.CancelTaskAsync(taskId, cancellationToken).ConfigureAwait(true);
                            cancelled++;
                        }
                        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                        {
                            throw;
                        }
                        catch (Exception)
                        {
                            failedToCancel++;
                        }
                    }
                    ActionMessage = failedToCancel == 0
                        ? $"已向 Mac Core 提交 {cancelled} 个任务的安全取消请求。"
                        : $"已提交 {cancelled} 个取消请求，另有 {failedToCancel} 个任务取消失败，请刷新后重试。";
                    break;

                case OperatorTaskListMode.Completed:
                    var hidden = await _session.HideTasksAsync(taskIds, cancellationToken).ConfigureAwait(true);
                    var hideFailed = hidden.Outcomes.Count(outcome => !outcome.Success || outcome.PendingCancel);
                    ActionMessage = hideFailed == 0
                        ? $"已将 {hidden.Outcomes.Count} 个任务移入已删除。"
                        : $"已处理 {hidden.Outcomes.Count} 个任务，其中 {hideFailed} 个未能移入已删除。";
                    break;

                case OperatorTaskListMode.Deleted:
                    var restored = await _session.RestoreTasksAsync(taskIds, cancellationToken).ConfigureAwait(true);
                    var restoreFailed = restored.Outcomes.Count(outcome => !outcome.Success || outcome.PendingCancel);
                    ActionMessage = restoreFailed == 0
                        ? $"已恢复 {restored.Outcomes.Count} 个任务。"
                        : $"已处理 {restored.Outcomes.Count} 个任务，其中 {restoreFailed} 个恢复失败。";
                    break;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            ActionMessage = _mode switch
            {
                OperatorTaskListMode.InProgress => "取消操作没有完成；任务状态仍由 Mac Core 保存。",
                OperatorTaskListMode.Completed => "移到已删除没有完成；任务状态仍由 Mac Core 保存。",
                OperatorTaskListMode.Deleted => "恢复操作没有完成；任务状态仍由 Mac Core 保存。",
                _ => "任务操作没有完成；任务状态仍由 Mac Core 保存。",
            };
        }
        finally
        {
            IsBusy = false;
        }
    }

    private string BuildBusyMessage(int count) => _mode switch
    {
        OperatorTaskListMode.InProgress => count == 1
            ? "正在取消任务……"
            : $"正在取消 {count} 个任务……",
        OperatorTaskListMode.Completed => count == 1
            ? "正在移到已删除……"
            : $"正在将 {count} 个任务移到已删除……",
        OperatorTaskListMode.Deleted => count == 1
            ? "正在恢复任务……"
            : $"正在恢复 {count} 个任务……",
        _ => "正在处理任务……",
    };

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
        RaisePropertyChanged(nameof(HasItems));
        RaisePropertyChanged(nameof(CanSelectAll));
        RaisePropertyChanged(nameof(CanClearSelection));
        RaisePropertyChanged(nameof(CanApplySelection));
    }

    private void RaiseActionProperties()
    {
        RaisePropertyChanged(nameof(CanSelectAll));
        RaisePropertyChanged(nameof(CanClearSelection));
        RaisePropertyChanged(nameof(CanApplySelection));
        RaisePropertyChanged(nameof(CanApplyAnyAction));
    }
}
