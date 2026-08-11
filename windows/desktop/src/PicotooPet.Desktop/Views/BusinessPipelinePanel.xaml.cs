using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Business Pipeline 面板只转发固定编排动作；不接受执行器、模型或路径参数。</summary>
public partial class BusinessPipelinePanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public BusinessPipelinePanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not BusinessPipelinePanelViewModel viewModel)
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
            // ── Smoke-test ViewModel intentionally has no live Mac session ─────────────
        }
        catch (Exception)
        {
            ShowSafeError(
                "Business Pipeline 读取失败",
                "端到端业务状态暂时无法读取；没有触发模型、ComfyUI 或付费 AI。详细信息由应用脱敏日志记录。");
        }
    }

    private async void Create_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateSelectedAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Reconcile_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ReconcileSelectedAsync(CancellationToken.None));

    private async void DownloadReturn_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.DownloadSelectedReturnPackageAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not BusinessPipelinePanelViewModel viewModel || viewModel.SelectedRun is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "取消所选 Business Pipeline？\n\n不会删除 Work / Result / Creative / Production Package，也不会删除原业务数据。",
            "确认取消端到端 Pipeline",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async Task RunAsync(Func<BusinessPipelinePanelViewModel, Task> action)
    {
        if (DataContext is not BusinessPipelinePanelViewModel viewModel)
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
                "Business Pipeline 操作失败",
                "操作未完成；不会自动切换付费 AI、云渲染或执行生产者代码。详细信息由应用脱敏日志记录。");
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
