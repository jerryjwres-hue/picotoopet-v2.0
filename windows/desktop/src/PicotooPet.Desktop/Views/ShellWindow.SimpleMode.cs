using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.Views;

public partial class ShellWindow
{
    private void SimpleHome_Click(object sender, RoutedEventArgs e) => ShowSimpleRoute(NavigationRoute.Dashboard);
    private void SimpleReview_Click(object sender, RoutedEventArgs e) => ShowSimpleRoute(NavigationRoute.Approvals);
    private void SimpleActive_Click(object sender, RoutedEventArgs e) => ShowSimpleRoute(NavigationRoute.TaskCenter);
    private void SimpleCompleted_Click(object sender, RoutedEventArgs e) => ShowSimpleRoute(NavigationRoute.Results);

    private void SimpleAdvanced_Click(object sender, RoutedEventArgs e)
    {
        AdvancedHomePanel.Visibility = Visibility.Visible;
    }

    private void AdvancedRoute_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string key })
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
            _ => NavigationRoute.Dashboard,
        };
        ShowSimpleRoute(route);
    }

    private void ShowSimpleRoute(NavigationRoute route)
    {
        AdvancedHomePanel.Visibility = Visibility.Collapsed;
        _viewModel.Navigate(route);
    }
}
