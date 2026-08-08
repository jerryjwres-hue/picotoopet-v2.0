using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>项目页只转发显式项目元数据动作。</summary>
public partial class ProjectsPage : System.Windows.Controls.UserControl
{
    private bool _loadedOnce;

    public ProjectsPage()
    {
        InitializeComponent();
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loadedOnce || DataContext is not ProjectsPageViewModel viewModel)
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
            ShowSafeError("读取项目失败", "项目列表暂时无法读取；详细信息由应用脱敏日志记录。");
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.RefreshAsync(CancellationToken.None));

    private async void Create_Click(object sender, RoutedEventArgs e) =>
        await RunAsync(viewModel => viewModel.CreateAsync(CancellationToken.None));

    private async void Archive_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not ProjectsPageViewModel viewModel || viewModel.SelectedProject is null)
        {
            return;
        }
        var answer = MessageBox.Show(
            Window.GetWindow(this),
            $"归档项目“{viewModel.SelectedProject.Title}”？\n\n只修改项目元数据，不删除工作目录或文件。",
            "确认归档项目",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No);
        if (answer != MessageBoxResult.Yes)
        {
            return;
        }
        await RunAsync(model => model.ArchiveSelectedAsync(CancellationToken.None));
    }

    private async Task RunAsync(Func<ProjectsPageViewModel, Task> action)
    {
        if (DataContext is not ProjectsPageViewModel viewModel)
        {
            return;
        }
        try
        {
            await action(viewModel);
        }
        catch (Exception)
        {
            ShowSafeError("项目操作失败", "项目操作未完成；不会删除用户文件，详细信息由应用脱敏日志记录。");
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
