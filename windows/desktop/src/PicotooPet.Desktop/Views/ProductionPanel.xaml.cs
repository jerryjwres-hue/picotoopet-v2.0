using System.Windows;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Services.QualityObservation;

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

    private async void ObserveVisuals_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ProductionPanelViewModel model) return;
        if (model.IsObservingVisuals) { model.CancelVisualObservation(); return; }
        await model.ObserveSelectedVisualsAsync(async (request, ct) =>
        {
            // The service runs on a worker thread; only this explicit click owns consent UI.
            return await Dispatcher.InvokeAsync(() =>
            {
                ct.ThrowIfCancellationRequested();
                if (DataContext != model || model.SelectedJob?.ProductionJobId != request.JobId) return new VisualReadConsent(false);
                var sources = string.Join("\n\n", request.Sources.Select(s =>
                    $"镜头 {s.ShotId} / 任务 {s.TaskId}\n{s.Path}\nBytes {s.Bytes} · SHA256 {s.Sha256}"));
                var read = MessageBox.Show(Window.GetWindow(this),
                    $"只读核对并 CPU 采样以下三段 WebM？\nJob {request.JobId}\n\n{sources}\n\n不会启动渲染、修改 C011 或生成 ACCEPT。",
                    "确认读取精确审片来源", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) == MessageBoxResult.Yes;
                ct.ThrowIfCancellationRequested();
                var transfer = read && request.VlmEndpoint is not null && MessageBox.Show(Window.GetWindow(this),
                    $"另行同意将三张缩放中间帧发送到已配置局域网模型？\n{request.VlmEndpoint}\n{request.VlmModel}\n\n不发送原视频；不下载模型；模型意见不是人工 ACCEPT。",
                    "单独确认帧传输", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) == MessageBoxResult.Yes;
                ct.ThrowIfCancellationRequested();
                return new VisualReadConsent(read, transfer);
            });
        }, CancellationToken.None);
    }

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
