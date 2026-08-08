using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>平台健康页只读取结构化事实。</summary>
public partial class HealthPage : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public HealthPage()
    {
        InitializeComponent();
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not HealthPageViewModel viewModel)
        {
            return;
        }
        _loadedOnce = true;
        try
        {
            await viewModel.RefreshAsync(CancellationToken.None);
        }
        catch (InvalidOperationException)
        {
            // Smoke-test ViewModel intentionally has no network Session.
        }
        catch (Exception)
        {
            ShowSafeError();
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not HealthPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await viewModel.RefreshAsync(CancellationToken.None);
        }
        catch (Exception)
        {
            ShowSafeError();
        }
    }

    private void ShowSafeError() =>
        MessageBox.Show(
            Window.GetWindow(this),
            "健康快照暂时无法读取；不会回退为伪造状态。",
            "读取健康状态失败",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
}
