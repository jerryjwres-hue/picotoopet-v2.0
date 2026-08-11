using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Production 面板只转发固定动作；不读取或执行自由 renderer 参数。</summary>
public partial class ProductionPanel : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public ProductionPanel()
    {
        InitializeComponent();
    }

    private async void Panel_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not ProductionPanelViewModel viewModel)
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
            // ── Smoke-test ViewModel intentionally has no live Mac/Comfy session ────────
        }
        catch (Exception)
        {
            ShowSafeError(
                "生产状态读取失败",
                "Production 状态暂时无法读取；没有启动任何 ComfyUI render。详细信息由应用脱敏日志记录。");
        }
    }

    private async void Create_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateSelectedAsync(CancellationToken.None));

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Preflight_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.PreflightAsync(CancellationToken.None));

    private async void Start_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ProductionPanelViewModel viewModel || viewModel.SelectedJob is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "启动所选 Production Job 的本地 ComfyUI 渲染？\n\n只会执行 Core Plan 指定的源码 allowlist workflow，不会切换云渲染或自动发布。",
            "确认启动本地生产",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.StartSelectedAsync(CancellationToken.None));
        }
    }

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ProductionPanelViewModel viewModel || viewModel.SelectedJob is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "取消所选 Production Job？\n\n不会删除 Creative Package、模型文件或已提交的内容寻址输出。",
            "确认取消 Production Job",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async Task RunAsync(Func<ProductionPanelViewModel, Task> action)
    {
        if (DataContext is not ProductionPanelViewModel viewModel)
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
                "本地生产操作失败",
                "操作未完成；不会切换云渲染或自动发布。详细信息由应用脱敏日志记录。");
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
