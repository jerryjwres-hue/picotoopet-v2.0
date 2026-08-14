using System.Windows;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>26.1 简单模式首页；只负责打开受限任务向导并导航到既有安全路由。</summary>
public partial class OperatorHomePage : System.Windows.Controls.UserControl
{
    public OperatorHomePage()
    {
        InitializeComponent();
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
            && Window.GetWindow(this) is PicotooPet.Desktop.Views.ShellWindow shell)
        {
            shell.NavigateFromOperator(route);
        }
        await Task.CompletedTask;
    }

    private void Review_Click(object sender, RoutedEventArgs e) =>
        Navigate(NavigationRoute.OperatorReview);

    private void Active_Click(object sender, RoutedEventArgs e) =>
        Navigate(NavigationRoute.OperatorInProgress);

    private void Completed_Click(object sender, RoutedEventArgs e) =>
        Navigate(NavigationRoute.OperatorCompleted);

    private void Navigate(NavigationRoute route)
    {
        if (Window.GetWindow(this) is PicotooPet.Desktop.Views.ShellWindow shell)
        {
            shell.NavigateFromOperator(route);
        }
    }
}
