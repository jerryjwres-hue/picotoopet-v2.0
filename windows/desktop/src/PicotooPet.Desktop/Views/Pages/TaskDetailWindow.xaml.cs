using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>任务详情窗口；加载已知固定结果合同，不打开任意文件。</summary>
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
        try
        {
            await _viewModel.LoadAsync();
        }
        catch (OperationCanceledException)
        {
            // Window lifecycle cancellation does not mutate the task or result.
        }
    }
}
