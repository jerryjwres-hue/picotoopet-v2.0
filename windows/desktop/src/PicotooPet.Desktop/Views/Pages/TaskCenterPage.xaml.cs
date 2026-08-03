using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>任务中心视图只转发显式用户动作；状态规则保留在 ViewModel 和 Mac Core。</summary>
public partial class TaskCenterPage : System.Windows.Controls.UserControl
{
    public TaskCenterPage()
    {
        InitializeComponent();
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
        catch (Exception exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                exception.Message,
                "创建系统诊断失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
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
        catch (Exception exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                exception.Message,
                "取消任务失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
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
        catch (Exception exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                exception.Message,
                "重试任务失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
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
        catch (Exception exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                exception.Message,
                "读取诊断结果失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}