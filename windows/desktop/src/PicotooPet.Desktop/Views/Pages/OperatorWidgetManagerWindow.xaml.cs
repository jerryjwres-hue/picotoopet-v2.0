using System.Windows;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views.Pages;

/// <summary>固定组件管理窗口；只转发显隐与排序操作。</summary>
public partial class OperatorWidgetManagerWindow : Window
{
    public OperatorWidgetManagerWindow(OperatorHomePageViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
    }

    private void Toggle_Click(object sender, RoutedEventArgs e) =>
        WithWidgetId(sender, static (viewModel, widgetId) => viewModel.ToggleWidget(widgetId));

    private void MoveUp_Click(object sender, RoutedEventArgs e) =>
        WithWidgetId(sender, static (viewModel, widgetId) => viewModel.MoveWidget(widgetId, -1));

    private void MoveDown_Click(object sender, RoutedEventArgs e) =>
        WithWidgetId(sender, static (viewModel, widgetId) => viewModel.MoveWidget(widgetId, 1));

    private void Close_Click(object sender, RoutedEventArgs e) => Close();

    private void WithWidgetId(
        object sender,
        Action<OperatorHomePageViewModel, string> action)
    {
        if (DataContext is not OperatorHomePageViewModel viewModel
            || sender is not System.Windows.Controls.Button { Tag: string widgetId })
        {
            return;
        }

        action(viewModel, widgetId);
    }
}
