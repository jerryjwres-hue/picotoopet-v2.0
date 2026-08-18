using System.Windows;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
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
    private readonly Dictionary<FrameworkElement, Action> _workComponentActions = new();

    public OperatorHomePage()
    {
        InitializeComponent();
        _resourceSampler = new WindowsResourceSampler();
        _resourceTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(2),
        };
        _resourceTimer.Tick += ResourceTimer_Tick;
        RecentTasksCard.PreviewMouseLeftButtonUp += RecentTasksCard_PreviewMouseLeftButtonUp;
        RecentTasksCard.PreviewMouseMove += RecentTasksCard_PreviewMouseMove;
        RecentTasksCard.MouseLeave += RecentTasksCard_MouseLeave;
        WorkComponentsCard.Loaded += WorkComponentsCard_Loaded;
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

    private void RecentTasksCard_PreviewMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        var task = FindRecentTaskCard(e.OriginalSource as DependencyObject);
        if (task is null)
        {
            return;
        }

        e.Handled = true;
        OpenRecentTask(task);
    }

    private void RecentTasksCard_PreviewMouseMove(object sender, MouseEventArgs e)
    {
        RecentTasksCard.Cursor = FindRecentTaskCard(e.OriginalSource as DependencyObject) is null
            ? System.Windows.Input.Cursors.Arrow
            : System.Windows.Input.Cursors.Hand;
    }

    private void RecentTasksCard_MouseLeave(object sender, MouseEventArgs e)
    {
        RecentTasksCard.Cursor = System.Windows.Input.Cursors.Arrow;
    }

    private OperatorTaskCard? FindRecentTaskCard(DependencyObject? source)
    {
        var current = source;
        while (current is not null && !ReferenceEquals(current, RecentTasksCard))
        {
            if (current is FrameworkElement { DataContext: OperatorTaskCard task })
            {
                return task;
            }

            current = GetParent(current);
        }

        return null;
    }

    /// <summary>保持现有卡片视觉，只把四张工作组件卡接入既有 Shell 路由。</summary>
    private void WorkComponentsCard_Loaded(object sender, RoutedEventArgs e)
    {
        var componentGrid = FindVisualDescendant<UniformGrid>(WorkComponentsCard);
        if (componentGrid is null || componentGrid.Children.Count < 4)
        {
            return;
        }

        ConfigureWorkComponent(
            componentGrid.Children[0] as FrameworkElement,
            ProjectsResearch_Click,
            "打开项目 / 调研入口");
        ConfigureWorkComponent(
            componentGrid.Children[1] as FrameworkElement,
            BusinessAnalysis_Click,
            "打开业务分析入口");
        ConfigureWorkComponent(
            componentGrid.Children[2] as FrameworkElement,
            AutomationEntry_Click,
            "打开自动化入口");
        ConfigureWorkComponent(
            componentGrid.Children[3] as FrameworkElement,
            ResultsReview_Click,
            "打开结果 / 审核入口");
    }

    private void ConfigureWorkComponent(
        FrameworkElement? element,
        Action action,
        string toolTip)
    {
        if (element is null || _workComponentActions.ContainsKey(element))
        {
            return;
        }

        _workComponentActions[element] = action;
        element.Cursor = System.Windows.Input.Cursors.Hand;
        element.Focusable = true;
        element.ToolTip = toolTip;
        element.PreviewMouseLeftButtonUp += WorkComponent_PreviewMouseLeftButtonUp;
        element.PreviewKeyDown += WorkComponent_PreviewKeyDown;
        element.MouseEnter += WorkComponent_MouseEnter;
        element.MouseLeave += WorkComponent_MouseLeave;
    }

    private void WorkComponent_PreviewMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (sender is FrameworkElement element
            && _workComponentActions.TryGetValue(element, out var action))
        {
            e.Handled = true;
            action();
        }
    }

    private void WorkComponent_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key is not (Key.Enter or Key.Space)
            || sender is not FrameworkElement element
            || !_workComponentActions.TryGetValue(element, out var action))
        {
            return;
        }

        e.Handled = true;
        action();
    }

    private static void WorkComponent_MouseEnter(object sender, MouseEventArgs e)
    {
        if (sender is FrameworkElement element)
        {
            element.Opacity = 0.90;
        }
    }

    private static void WorkComponent_MouseLeave(object sender, MouseEventArgs e)
    {
        if (sender is FrameworkElement element)
        {
            element.Opacity = 1.0;
        }
    }

    private static T? FindVisualDescendant<T>(DependencyObject parent)
        where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(parent); index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is T match)
            {
                return match;
            }

            var nested = FindVisualDescendant<T>(child);
            if (nested is not null)
            {
                return nested;
            }
        }

        return null;
    }

    private void ProjectsResearch_Click() => Navigate(NavigationRoute.Projects);
    private void BusinessAnalysis_Click() => Navigate(NavigationRoute.BusinessAutomation);
    private void AutomationEntry_Click() => Navigate(NavigationRoute.Automation);
    private void ResultsReview_Click() => Navigate(NavigationRoute.Results);

    private static DependencyObject? GetParent(DependencyObject current)
    {
        if (current is FrameworkContentElement contentElement)
        {
            return contentElement.Parent;
        }

        if (current is Visual)
        {
            return VisualTreeHelper.GetParent(current);
        }

        return LogicalTreeHelper.GetParent(current);
    }

    private void OpenRecentTask(OperatorTaskCard task)
    {
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
