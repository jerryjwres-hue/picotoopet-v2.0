using System.Windows;
using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.Views;

// 简单模式使用六入口，并保留既有高级页面入口。
public partial class ShellWindow
{
    private void SimpleHome_Click(object sender, RoutedEventArgs e) =>
        ShowSimpleRoute(NavigationRoute.OperatorHome);

    private void SimpleReview_Click(object sender, RoutedEventArgs e) =>
        ShowSimpleRoute(NavigationRoute.OperatorReview);

    private void SimpleActive_Click(object sender, RoutedEventArgs e) =>
        ShowSimpleRoute(NavigationRoute.OperatorInProgress);

    private void SimpleCompleted_Click(object sender, RoutedEventArgs e) =>
        ShowSimpleRoute(NavigationRoute.OperatorCompleted);

    private void SimpleDeleted_Click(object sender, RoutedEventArgs e) =>
        ShowSimpleRoute(NavigationRoute.OperatorDeleted);

    private void SimpleAdvanced_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.Navigate(NavigationRoute.AdvancedHome);
        AdvancedHomePanel.Visibility = Visibility.Visible;
    }

    private void AdvancedRoute_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { Tag: string key })
        {
            return;
        }

        var route = key switch
        {
            "Projects" => NavigationRoute.Projects,
            "TaskCenter" => NavigationRoute.TaskCenter,
            "Results" => NavigationRoute.Results,
            "Approvals" => NavigationRoute.Approvals,
            "CloudDevelopment" => NavigationRoute.CloudDevelopment,
            "Automation" => NavigationRoute.Automation,
            "BusinessAutomation" => NavigationRoute.BusinessAutomation,
            "Health" => NavigationRoute.Health,
            "Diagnostics" => NavigationRoute.Diagnostics,
            "Settings" => NavigationRoute.Settings,
            _ => NavigationRoute.AdvancedHome,
        };
        ShowSimpleRoute(route);
    }

    internal void NavigateFromOperator(NavigationRoute route) => ShowSimpleRoute(route);

    private void ShowSimpleRoute(NavigationRoute route)
    {
        AdvancedHomePanel.Visibility = Visibility.Collapsed;
        _viewModel.Navigate(route);
    }
}
