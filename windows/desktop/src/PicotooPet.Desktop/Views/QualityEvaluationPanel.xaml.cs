using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>质量评估面板只转发 snapshot/evaluation/review 事实动作；不持有运行策略或执行配置。</summary>
public partial class QualityEvaluationPanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public QualityEvaluationPanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not QualityEvaluationPanelViewModel viewModel)
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
                "质量评估读取失败",
                "质量评估暂时无法读取；没有调用本地/付费 AI，也没有修改任何运行策略。详细信息由应用脱敏日志记录。");
        }
    }

    private async void CreateSnapshot_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateSnapshotAsync(CancellationToken.None));

    private async void Evaluate_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.EvaluateAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Reviewed_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.MarkReviewedAsync(CancellationToken.None));

    private async void AcceptForShadow_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.AcceptForShadowAsync(CancellationToken.None));

    private async void Reject_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RejectAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CancelAsync(CancellationToken.None));

    private async Task RunAsync(Func<QualityEvaluationPanelViewModel, Task> action)
    {
        if (DataContext is not QualityEvaluationPanelViewModel viewModel)
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
                "质量评估操作失败",
                "操作未完成；不会自动修改 Prompt/Model/Provider/Budget，也不会触发 Paid-AI 或 Shadow 执行。详细信息由应用脱敏日志记录。");
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
