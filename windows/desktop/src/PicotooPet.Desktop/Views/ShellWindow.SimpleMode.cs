using System.Windows;
using PicotooPet.Desktop.Navigation;

namespace PicotooPet.Desktop.Views;

// 26.1 简单模式使用固定五入口，并保留既有高级页面入口。
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

    private void SimpleAdvanced_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.Navigate(NavigationRoute.AdvancedHome);
        AdvancedHomePanel.Visibility = Visibility.Visible;
        UpdateSimpleNavSelection(NavigationRoute.AdvancedHome);
    }

    private void AdvancedRoute_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { Tag: string key })
        {
            return;
        }

        var route = key switch
        {
            "Projects"           => NavigationRoute.Projects,
            "TaskCenter"         => NavigationRoute.TaskCenter,
            "Results"            => NavigationRoute.Results,
            "Approvals"          => NavigationRoute.Approvals,
            "CloudDevelopment"   => NavigationRoute.CloudDevelopment,
            "Automation"         => NavigationRoute.Automation,
            "BusinessAutomation" => NavigationRoute.BusinessAutomation,
            "Health"             => NavigationRoute.Health,
            "Diagnostics"        => NavigationRoute.Diagnostics,
            "Settings"           => NavigationRoute.Settings,
            _                    => NavigationRoute.AdvancedHome,
        };
        ShowSimpleRoute(route);
    }

    internal void NavigateFromOperator(NavigationRoute route) => ShowSimpleRoute(route);

    private void ShowSimpleRoute(NavigationRoute route)
    {
        AdvancedHomePanel.Visibility = Visibility.Collapsed;
        _viewModel.Navigate(route);
        UpdateSimpleNavSelection(route);
    }

    /// <summary>只改变五个固定导航按钮的样式，不改变路由或权限。</summary>
    private void UpdateSimpleNavSelection(NavigationRoute route)
    {
        if (FindResource("SimpleNavButtonStyle") is not Style normalStyle
            || FindResource("SimpleNavSelectedButtonStyle") is not Style selectedStyle)
        {
            return;
        }

        var selectedButton = route switch
        {
            NavigationRoute.OperatorHome       => SimpleHomeButton,
            NavigationRoute.OperatorReview     => SimpleReviewButton,
            NavigationRoute.OperatorInProgress => SimpleActiveButton,
            NavigationRoute.OperatorCompleted  => SimpleCompletedButton,
            _                                  => SimpleAdvancedButton,
        };

        var buttons = new[]
        {
            SimpleHomeButton,
            SimpleReviewButton,
            SimpleActiveButton,
            SimpleCompletedButton,
            SimpleAdvancedButton,
        };
        foreach (var button in buttons)
        {
            button.Style = ReferenceEquals(button, selectedButton) ? selectedStyle : normalStyle;
        }
    }
}
