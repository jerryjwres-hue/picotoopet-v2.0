using System.Windows;
using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.Views;

// 简单模式导航由 ShellViewModel.NavigationItems + ListBox 双向选择唯一驱动。
public partial class ShellWindow
{
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
        _viewModel.Navigate(route);
    }

    internal void NavigateFromOperator(NavigationRoute route) =>
        _viewModel.Navigate(route);
}
