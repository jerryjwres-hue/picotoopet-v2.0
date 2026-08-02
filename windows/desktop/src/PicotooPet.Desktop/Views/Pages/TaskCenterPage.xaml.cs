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

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not TaskCenterPageViewModel viewModel)
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
}
