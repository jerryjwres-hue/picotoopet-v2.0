using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>简单模式首页；任务入口只调用既有安全路由或统一 TaskDetail。</summary>
public partial class OperatorHomePage : System.Windows.Controls.UserControl
{
    private readonly WindowsResourceSampler _resourceSampler;
    private readonly DispatcherTimer _resourceTimer;

    public OperatorHomePage()
    {
        InitializeComponent();
        _resourceSampler = new WindowsResourceSampler();
        _resourceTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(2),
        };
        _resourceTimer.Tick += ResourceTimer_Tick;
        Loaded += OperatorHomePage_Loaded;
        Unloaded += OperatorHomePage_Unloaded;
    }

    private void OperatorHomePage_Loaded(object sender, RoutedEventArgs e)
    {
        SampleResources();
        _resourceTimer.Start();
    }

    private void OperatorHomePage_Unloaded(object sender, RoutedEventArgs e) => _resourceTimer.Stop();

    private void ResourceTimer_Tick(object? sender, EventArgs e) => SampleResources();

    private void SampleResources()
    {
        if (DataContext is not OperatorHomePageViewModel viewModel)
        {
            return;
        }
        try
        {
            viewModel.UpdateResourceSnapshot(_resourceSampler.Sample());
        }
        catch (Exception)
        {
            viewModel.UpdateResourceSnapshot(new WindowsResourceSnapshot(null, null, null, DateTimeOffset.UtcNow));
        }
    }

    private async void NewTask_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel)
        {
            return;
        }

        var wizardViewModel = viewModel.CreateNewTaskWizard();
        var window = new NewTaskWizardWindow(wizardViewModel)
        {
            Owner = Window.GetWindow(this),
        };
        var result = window.ShowDialog();
        if (result == true
            && wizardViewModel.RequestedRoute is NavigationRoute route
            && Window.GetWindow(this) is ShellWindow shell)
        {
            shell.NavigateFromOperator(route);
        }
        await Task.CompletedTask;
    }

    private void RecentTask_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { DataContext: OperatorTaskCard task })
        {
            return;
        }

        try
        {
            var gateway = TaskDetailGatewayContext.GetGateway(this)
                ?? throw new InvalidOperationException("任务详情服务尚未就绪。");
            TaskDetailViewModel detailViewModel = gateway.Create(task.TaskId);
            new TaskDetailWindow(detailViewModel)
            {
                Owner = Window.GetWindow(this),
            }.Show();
        }
        catch (Exception)
        {
            MessageBox.Show(
                Window.GetWindow(this),
                "任务详情暂时无法打开。任务本身没有被修改，请刷新列表后重试。",
                "无法打开任务",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private void Review_Click(object sender, RoutedEventArgs e) => Navigate(NavigationRoute.OperatorReview);
    private void Active_Click(object sender, RoutedEventArgs e) => Navigate(NavigationRoute.OperatorInProgress);
    private void Completed_Click(object sender, RoutedEventArgs e) => Navigate(NavigationRoute.OperatorCompleted);

    private void Navigate(NavigationRoute route)
    {
        if (Window.GetWindow(this) is ShellWindow shell)
        {
            shell.NavigateFromOperator(route);
        }
    }
}
