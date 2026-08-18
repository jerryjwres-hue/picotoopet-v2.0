using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>简单模式任务列表交互；任务事实和写操作仍由 ViewModel/Mac Core 管理。</summary>
public partial class OperatorTaskListPage : System.Windows.Controls.UserControl
{
    public OperatorTaskListPage()
    {
        InitializeComponent();
    }

    private void SelectAll_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is OperatorTaskListPageViewModel viewModel)
        {
            viewModel.SelectAllVisible(selected: true);
        }
    }

    private void ClearSelection_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is OperatorTaskListPageViewModel viewModel)
        {
            viewModel.SelectAllVisible(selected: false);
        }
    }

    private void KeywordSearchBox_KeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key != Key.Enter || DataContext is not OperatorTaskListPageViewModel viewModel)
        {
            return;
        }

        viewModel.ApplyFilters();
        e.Handled = true;
    }

    private void ApplyFilters_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is OperatorTaskListPageViewModel viewModel)
        {
            viewModel.ApplyFilters();
        }
    }

    private void ClearFilters_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is not OperatorTaskListPageViewModel viewModel)
        {
            return;
        }

        viewModel.ClearFilters();
        KeywordSearchBox.Focus();
    }

    private async void BulkAction_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is not OperatorTaskListPageViewModel viewModel
            || !viewModel.HasSelection)
        {
            return;
        }
        if (!ConfirmAction(viewModel, viewModel.SelectedCount, taskTitle: null))
        {
            return;
        }
        await viewModel.ApplySelectedActionAsync();
    }

    private async void SingleAction_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (sender is not System.Windows.FrameworkElement element
            || element.DataContext is not OperatorTaskListItem item
            || DataContext is not OperatorTaskListPageViewModel viewModel)
        {
            return;
        }
        if (!ConfirmAction(viewModel, count: 1, item.Title))
        {
            return;
        }
        await viewModel.ApplySingleActionAsync(item.TaskId);
    }

    /// <summary>不同任务桶使用不同语义；进行中只取消，不伪装成删除。</summary>
    private static bool ConfirmAction(
        OperatorTaskListPageViewModel viewModel,
        int count,
        string? taskTitle)
    {
        if (viewModel.IsDeletedMode)
        {
            return true;
        }

        var subject = taskTitle is null
            ? $"{count} 个已选择任务"
            : $"“{taskTitle}”";
        string message;
        string caption;
        if (viewModel.IsInProgressMode)
        {
            message = $"取消{subject}？\n\n运行中的任务会请求 Mac Core / Worker 安全停止；任务记录不会被直接删除。";
            caption = "确认取消任务";
        }
        else
        {
            message = $"将{subject}移到“已删除”？\n\n这是可恢复的软删除，Mac Core 仍保留任务事实。";
            caption = "确认移到已删除";
        }

        return System.Windows.MessageBox.Show(
                   message,
                   caption,
                   System.Windows.MessageBoxButton.YesNo,
                   System.Windows.MessageBoxImage.Question)
               == System.Windows.MessageBoxResult.Yes;
    }

    private void OpenTask_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (sender is not System.Windows.FrameworkElement element
            || element.DataContext is not OperatorTaskListItem item
            || DataContext is not OperatorTaskListPageViewModel viewModel)
        {
            return;
        }
        try
        {
            var detail = new TaskDetailWindow(viewModel.CreateDetail(item.TaskId))
            {
                Owner = System.Windows.Window.GetWindow(this),
            };
            detail.ShowDialog();
        }
        catch (Exception)
        {
            System.Windows.MessageBox.Show(
                "任务详情暂时无法安全显示。任务本身没有被修改，请刷新列表后重试。",
                "任务详情暂时不可用",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Information);
        }
    }
}
