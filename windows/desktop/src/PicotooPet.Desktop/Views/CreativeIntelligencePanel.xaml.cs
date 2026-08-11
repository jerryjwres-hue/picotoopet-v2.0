using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Creative Intelligence 只转发固定安全动作。</summary>
public partial class CreativeIntelligencePanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public CreativeIntelligencePanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not CreativeIntelligencePanelViewModel viewModel)
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
            // Smoke-test ViewModel intentionally has no live Session.
        }
        catch (Exception)
        {
            ShowSafeError("创意智能读取失败", "Creative Intelligence 状态暂时无法读取；详细信息由应用脱敏日志记录。");
        }
    }

    private async void Prepare_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.PrepareAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel || viewModel.SelectedJob is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "取消所选 Creative Job？\n\n只取消 PicotooPet 创意任务，不删除来源 Result Package。",
            "确认取消 Creative Job",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async void ExportPackage_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ExportSelectedPackageAsync(CancellationToken.None));

    private async void ExportHandoff_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ExportSelectedHandoffAsync(CancellationToken.None));

    private async Task RunAsync(Func<CreativeIntelligencePanelViewModel, Task> action)
    {
        if (DataContext is not CreativeIntelligencePanelViewModel viewModel)
        {
            return;
        }
        try
        {
            await action(viewModel);
        }
        catch (Exception)
        {
            ShowSafeError("创意智能操作失败", "操作未完成；不会调用付费 AI 或执行 ComfyUI，详细信息由应用脱敏日志记录。");
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
