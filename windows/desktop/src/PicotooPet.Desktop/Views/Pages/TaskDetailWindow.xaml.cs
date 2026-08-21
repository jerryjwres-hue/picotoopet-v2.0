using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>任务详情窗口；加载固定结果合同，并在窗口存活期间持续刷新 Core 耐久进度。</summary>
public partial class TaskDetailWindow : System.Windows.Window
{
    private readonly TaskDetailViewModel _viewModel;
    private readonly CancellationTokenSource _progressLifetime = new();
    private Task? _progressLoopTask;

    public TaskDetailWindow(TaskDetailViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        DataContext = _viewModel;
        Loaded += OnLoaded;
        Closed += OnClosed;
    }

    private async void OnLoaded(object sender, System.Windows.RoutedEventArgs e)
    {
        Loaded -= OnLoaded;
        try
        {
            await _viewModel.LoadAsync(_progressLifetime.Token);
            _progressLoopTask = _viewModel.RunProgressLoopAsync(_progressLifetime.Token);
        }
        catch (OperationCanceledException) when (_progressLifetime.IsCancellationRequested)
        {
            // Window lifecycle cancellation does not mutate the task or result.
        }
    }

    private async void OnClosed(object? sender, EventArgs e)
    {
        Closed -= OnClosed;
        _progressLifetime.Cancel();
        try
        {
            if (_progressLoopTask is not null)
            {
                await _progressLoopTask;
            }
        }
        catch (OperationCanceledException) when (_progressLifetime.IsCancellationRequested)
        {
            // 正常关闭只停止本窗口的只读轮询，不取消 Mac Core 中的任务。
        }
        finally
        {
            _progressLifetime.Dispose();
        }
    }
}
