using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>审批页面只转发显式加载、批准和拒绝动作。</summary>
public partial class ApprovalsPage : System.Windows.Controls.UserControl
{
    public ApprovalsPage()
    {
        InitializeComponent();
    }

    private async void ApprovalsPage_Loaded(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ApprovalsPageViewModel viewModel || viewModel.IsLoaded)
        {
            return;
        }
        await RunSafelyAsync(
            () => viewModel.LoadAsync(CancellationToken.None),
            "读取审批列表失败");
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ApprovalsPageViewModel viewModel)
        {
            return;
        }
        await RunSafelyAsync(
            () => viewModel.LoadAsync(CancellationToken.None),
            "刷新审批列表失败");
    }

    private async void Approve_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ApprovalsPageViewModel viewModel)
        {
            return;
        }
        await RunSafelyAsync(
            () => viewModel.ApproveSelectedAsync(CancellationToken.None),
            "批准审批失败");
    }

    private async void Reject_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ApprovalsPageViewModel viewModel)
        {
            return;
        }
        await RunSafelyAsync(
            () => viewModel.RejectSelectedAsync(CancellationToken.None),
            "拒绝审批失败");
    }

    private async Task RunSafelyAsync(Func<Task> action, string title)
    {
        try
        {
            await action();
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "审批操作未提交或服务端未确认。请刷新列表后按当前摘要重新检查；其他页面仍可使用。",
                title,
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}
