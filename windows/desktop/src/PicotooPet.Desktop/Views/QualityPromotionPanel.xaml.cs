using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Promotion 面板只转发闭合治理动作；exact digest 与资格由 Mac Core 强校验。</summary>
public partial class QualityPromotionPanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public QualityPromotionPanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not QualityPromotionPanelViewModel viewModel)
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
            // Smoke-test boundary       Smoke ViewModel intentionally has no live Mac Core session.
        }
        catch (Exception)
        {
            ShowSafeError(
                "Promotion 读取失败",
                "Promotion 暂时无法读取；不会修改 Prompt/Model/Provider/Budget/Workflow，也不会触发任何外部执行。详细信息由应用脱敏日志记录。");
        }
    }

    private async void Create_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Reconcile_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ReconcileAsync(CancellationToken.None));

    private async void ApproveActivation_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ApproveActivationAsync(CancellationToken.None));

    private async void RejectActivation_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RejectActivationAsync(CancellationToken.None));

    private async void CancelActivation_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CancelActivationAsync(CancellationToken.None));

    private async void RequestRollback_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RequestRollbackAsync(CancellationToken.None));

    private async void ApproveRollback_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ApproveRollbackAsync(CancellationToken.None));

    private async void RejectRollback_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RejectRollbackAsync(CancellationToken.None));

    private async void CancelRollback_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CancelRollbackAsync(CancellationToken.None));

    private async Task RunAsync(Func<QualityPromotionPanelViewModel, Task> action)
    {
        if (DataContext is not QualityPromotionPanelViewModel viewModel)
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
                "Promotion 操作失败",
                "操作未完成；系统不会自动晋级、回滚或修改任何 runtime policy。详细信息由应用脱敏日志记录。");
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
