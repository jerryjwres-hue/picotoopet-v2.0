using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>任务详情窗口；加载固定结果合同，并在窗口存活期间持续刷新 Core 耐久进度。</summary>
public partial class TaskDetailWindow : System.Windows.Window
{
    private readonly TaskDetailViewModel _viewModel;

    public TaskDetailWindow(TaskDetailViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        DataContext = _viewModel;
        Loaded += OnLoaded;
    }

    private async void OnLoaded(object sender, System.Windows.RoutedEventArgs e)
    {
        Loaded -= OnLoaded;
        using var progressLifetime = new CancellationTokenSource();
        EventHandler closedHandler = (_, _) => OnClosed(progressLifetime);
        Closed += closedHandler;
        try
        {
            await _viewModel.LoadAsync(progressLifetime.Token);
            await _viewModel.RunProgressLoopAsync(progressLifetime.Token);
        }
        catch (OperationCanceledException) when (progressLifetime.IsCancellationRequested)
        {
            // 正常关闭只停止本窗口的只读轮询，不取消 Mac Core 中的任务。
        }
        finally
        {
            Closed -= closedHandler;
        }
    }

    private static void OnClosed(CancellationTokenSource progressLifetime)
    {
        progressLifetime.Cancel();
    }
}
