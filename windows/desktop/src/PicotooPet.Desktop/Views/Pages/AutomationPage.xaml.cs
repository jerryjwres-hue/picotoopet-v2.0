using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>自动化页只转发固定 Workflow API；不接受任意命令。</summary>
public partial class AutomationPage : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public AutomationPage()
    {
        InitializeComponent();
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not AutomationPageViewModel viewModel)
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
            // Smoke-test ViewModel intentionally has no network Session.
        }
        catch (Exception)
        {
            ShowSafeError("读取自动化失败", "工作流列表暂时无法读取；状态仍保存在 Mac Core。", MessageBoxImage.Error);
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(model => model.RefreshAsync(CancellationToken.None));

    private async void CreateSafeWorkflow_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(model => model.CreateSafeDiagnosticWorkflowAsync(CancellationToken.None));

    private async void Reconcile_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(model => model.ReconcileSelectedAsync(CancellationToken.None));

    private async void Pause_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(model => model.PauseSelectedAsync(CancellationToken.None));

    private async void Resume_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(model => model.ResumeSelectedAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not AutomationPageViewModel viewModel || viewModel.SelectedWorkflow is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            $"取消工作流“{viewModel.SelectedWorkflow.Name}”？\n\n未运行步骤会进入 Cancelled；已经在 Worker 中执行的任务通过现有任务取消状态机停止。",
            "确认取消工作流",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async Task RunAsync(Func<AutomationPageViewModel, Task> action)
    {
        if (DataContext is not AutomationPageViewModel viewModel)
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
                "自动化操作失败",
                "请求未完成；Mac Core 的耐久状态不会被客户端伪造或覆盖。",
                MessageBoxImage.Error);
        }
    }

    private void ShowSafeError(string title, string message, MessageBoxImage image) =>
        MessageBox.Show(
            Window.GetWindow(this),
            message,
            title,
            MessageBoxButton.OK,
            image);
}
