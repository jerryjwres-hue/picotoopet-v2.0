using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>业务自动化页只转发固定安全动作，不承载模型、Prompt 或路径输入。</summary>
public partial class BusinessAutomationPage : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public BusinessAutomationPage()
    {
        InitializeComponent();
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not BusinessAutomationPageViewModel viewModel)
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
            // Smoke-test ViewModel intentionally has no live Session/Inbox.
        }
        catch (Exception)
        {
            ShowSafeError("业务自动化读取失败", "业务自动化状态暂时无法读取；详细信息由应用脱敏日志记录。");
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void SubmitInbox_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.SubmitInboxAsync(CancellationToken.None));

    private async void DeliverResult_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.DeliverResultsAsync(CancellationToken.None));

    private async void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not BusinessAutomationPageViewModel viewModel
            || viewModel.SelectedPackage is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            "取消所选业务包？\n\n只终止 PicotooPet 的耐久业务任务，不删除原业务程序文件或数据。",
            "确认取消业务包",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer == MessageBoxResult.Yes)
        {
            await RunAsync(model => model.CancelSelectedAsync(CancellationToken.None));
        }
    }

    private async void ExportHandoff_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.ExportSelectedDeepAiHandoffAsync(CancellationToken.None));

    private async Task RunAsync(Func<BusinessAutomationPageViewModel, Task> action)
    {
        if (DataContext is not BusinessAutomationPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await action(viewModel);
        }
        catch (Exception)
        {
            ShowSafeError("业务自动化操作失败", "操作未完成；不会调用付费 AI 或执行生产者代码，详细信息由应用脱敏日志记录。");
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
