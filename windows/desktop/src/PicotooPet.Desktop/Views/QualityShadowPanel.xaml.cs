using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Shadow 面板只转发 deterministic replay/review 动作；不持有任何可执行策略。</summary>
public partial class QualityShadowPanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public QualityShadowPanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not QualityShadowPanelViewModel viewModel)
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
                "Shadow 读取失败",
                "Shadow 暂时无法读取；没有调用本地/付费 AI，也没有修改任何运行策略。详细信息由应用脱敏日志记录。");
        }
    }

    private async void Create_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateAsync(CancellationToken.None));

    private async void Reconcile_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ReconcileAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Reviewed_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.MarkReviewedAsync(CancellationToken.None));

    private async void AcceptForPromotionReview_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.AcceptForPromotionReviewAsync(CancellationToken.None));

    private async void Reject_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RejectAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CancelAsync(CancellationToken.None));

    private async Task RunAsync(Func<QualityShadowPanelViewModel, Task> action)
    {
        if (DataContext is not QualityShadowPanelViewModel viewModel)
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
                "Shadow 操作失败",
                "操作未完成；不会执行 Prompt/Model/Provider/Budget 变更，也不会触发 Paid-AI、ComfyUI 或自动 Promotion。详细信息由应用脱敏日志记录。");
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
