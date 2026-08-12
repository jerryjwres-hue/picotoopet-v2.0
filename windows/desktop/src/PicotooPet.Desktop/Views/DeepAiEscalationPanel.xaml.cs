using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Deep-AI 面板只转发准备/读取/反馈动作；不持有 provider execution 配置。</summary>
public partial class DeepAiEscalationPanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public DeepAiEscalationPanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not DeepAiEscalationPanelViewModel viewModel)
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
            // Smoke-test ViewModel intentionally has no live Mac Core session.
        }
        catch (Exception)
        {
            ShowSafeError(
                "Deep-AI 状态读取失败",
                "Deep-AI 状态暂时无法读取；没有触发任何付费 Provider 调用。详细信息由应用脱敏日志记录。");
        }
    }

    private async void Prepare_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.PrepareSelectedSourceAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Reconcile_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ReconcileSelectedAsync(CancellationToken.None));

    private async void Accepted_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RecordAcceptedAsync(CancellationToken.None));

    private async void Rejected_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RecordRejectedAsync(CancellationToken.None));

    private async void Modified_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RecordModifiedAsync(CancellationToken.None));

    private async Task RunAsync(Func<DeepAiEscalationPanelViewModel, Task> action)
    {
        if (DataContext is not DeepAiEscalationPanelViewModel viewModel)
        {
            return;
        }
        try
        {
            await action(viewModel);
        }
        catch (Exception)
        {
            ShowSafeError(
                "Deep-AI 操作失败",
                "操作未完成；不会自动提高预算、切换 Provider 或发起新的付费调用。详细信息由应用脱敏日志记录。");
        }
    }

    private void ShowSafeError(string title, string message) =>
        MessageBox.Show(
            Window.GetWindow(this),
            message,
            title,
            MessageBoxButton.OK,
            MessageBoxImage.Error);
}
