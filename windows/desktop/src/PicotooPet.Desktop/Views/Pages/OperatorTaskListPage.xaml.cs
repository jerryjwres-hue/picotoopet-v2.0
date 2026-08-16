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

    private async void BulkAction_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (DataContext is not OperatorTaskListPageViewModel viewModel
            || !viewModel.HasSelection)
        {
            return;
        }
        if (!viewModel.IsDeletedMode)
        {
            var decision = System.Windows.MessageBox.Show(
                $"将 {viewModel.SelectedCount} 个任务安全删除？\n\n活动任务会先取消，之后进入“已删除”，可以恢复。",
                "确认安全删除",
                System.Windows.MessageBoxButton.YesNo,
                System.Windows.MessageBoxImage.Question);
            if (decision != System.Windows.MessageBoxResult.Yes)
            {
                return;
            }
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
        if (!viewModel.IsDeletedMode)
        {
            var decision = System.Windows.MessageBox.Show(
                $"安全删除“{item.Title}”？\n\n任务不会物理删除，可在“已删除”中恢复。",
                "确认安全删除",
                System.Windows.MessageBoxButton.YesNo,
                System.Windows.MessageBoxImage.Question);
            if (decision != System.Windows.MessageBoxResult.Yes)
            {
                return;
            }
        }
        await viewModel.ApplySingleActionAsync(item.TaskId);
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
