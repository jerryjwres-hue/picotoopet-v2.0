using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>诊断页只读取结构化安全事实。</summary>
public partial class DiagnosticsPage : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public DiagnosticsPage()
    {
        InitializeComponent();
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not DiagnosticsPageViewModel viewModel)
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
        if (DataContext is not DiagnosticsPageViewModel viewModel)
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
            "结构化诊断事实暂时无法读取；应用不会退回到抓取日志正文或用户文件。",
            "读取诊断失败",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
}
