using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>简单模式“进行中/已完成”列表；不复制或持久化任务状态。</summary>
public sealed class OperatorTaskListPageViewModel : PageViewModel
{
    private readonly bool _completed;
    private IReadOnlyList<OperatorTaskCard> _items = Array.Empty<OperatorTaskCard>();
    private string _emptyMessage = string.Empty;

    public OperatorTaskListPageViewModel(
        string title,
        bool completed,
        ControlCenterSessionSnapshot snapshot)
        : base(title)
    {
        _completed = completed;
        UpdateSnapshot(snapshot);
    }

    public IReadOnlyList<OperatorTaskCard> Items
    {
        get => _items;
        private set => SetProperty(ref _items, value);
    }

    public string EmptyMessage
    {
        get => _emptyMessage;
        private set => SetProperty(ref _emptyMessage, value);
    }

    public void UpdateSnapshot(ControlCenterSessionSnapshot snapshot)
    {
        var projection = OperatorProjection.FromSnapshot(snapshot);
        Items = _completed ? projection.Completed : projection.InProgress;
        EmptyMessage = Items.Count == 0
            ? _completed
                ? "还没有已结束的任务。"
                : "现在没有正在处理的任务。"
            : string.Empty;
    }
}
