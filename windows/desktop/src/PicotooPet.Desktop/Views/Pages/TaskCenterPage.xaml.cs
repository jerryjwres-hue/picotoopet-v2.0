using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>任务中心视图只转发显式用户动作；原始异常仅由 Session 写入脱敏日志。</summary>
public partial class TaskCenterPage : System.Windows.Controls.UserControl
{
    public TaskCenterPage()
    {
        InitializeComponent();
    }

    private void TaskList_DoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is not ListView listView
            || e.OriginalSource is not DependencyObject source
            || ItemsControl.ContainerFromElement(listView, source) is not ListViewItem row)
        {
            return;
        }

        listView.SelectedItem = row.DataContext;
        OpenSelectedTaskDetail();
    }

    private void OpenTaskDetail_Click(object sender, RoutedEventArgs e)
    {
        OpenSelectedTaskDetail();
    }

    private void OpenSelectedTaskDetail()
    {
        if (DataContext is not TaskCenterPageViewModel { SelectedTask: { } task })
        {
            MessageBox.Show(Window.GetWindow(this), "请先选择一个任务。", "查看任务", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        try
        {
            var gateway = TaskDetailGatewayContext.GetGateway(this)
                ?? throw new InvalidOperationException("任务详情服务尚未就绪。");
            TaskDetailViewModel detailViewModel = gateway.Create(task.TaskId);
            new TaskDetailWindow(detailViewModel)
            {
                Owner = Window.GetWindow(this),
            }.Show();
        }
        catch (Exception)
        {
            ShowSafeError("无法打开任务", "任务详情暂时无法打开。任务本身没有被修改，请刷新后重试。");
        }
    }

    private async void CreateDiagnostic_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not TaskCenterPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await viewModel.CreateDiagnosticAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError("创建系统诊断失败", "系统诊断任务未能创建。详细信息已写入脱敏日志，请稍后重试。");
        }
    }

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not TaskCenterPageViewModel viewModel
            || viewModel.SelectedTask is null)
        {
            return;
        }

        var confirmation = MessageBox.Show(
            Window.GetWindow(this),
            $"确定取消任务 {viewModel.SelectedTask.TaskId}？\n\n如果任务正在运行，Mac Worker 会先安全停止子进程，再提交唯一取消终态。",
            "确认取消任务",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (confirmation != MessageBoxResult.Yes)
        {
            return;
        }

        try
        {
            await viewModel.CancelSelectedAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError("取消任务失败", "取消请求未能完成。任务仍由 Mac Core 的状态机管理，详细信息已写入脱敏日志。");
        }
    }

    private async void Retry_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not TaskCenterPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await viewModel.RetrySelectedAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError("重试任务失败", "重试子任务未能创建。原任务不会被重新打开，详细信息已写入脱敏日志。");
        }
    }

    private async void ViewDiagnosticResult_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not TaskCenterPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await viewModel.LoadSelectedDiagnosticResultAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError("读取诊断结果失败", "诊断结果无法安全显示。详细信息已写入脱敏日志，任务结果不会被修改。");
        }
    }

    private void ShowSafeError(string title, string message)
    {
        MessageBox.Show(Window.GetWindow(this), message, title, MessageBoxButton.OK, MessageBoxImage.Error);
    }
}
