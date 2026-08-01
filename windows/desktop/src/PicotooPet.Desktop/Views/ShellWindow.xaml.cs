using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Shell 视图只处理窗口生命周期、路由命令和 PasswordBox 密文转交。</summary>
public partial class ShellWindow : Window
{
    private readonly ShellViewModel _viewModel;
    private readonly ControlCenterSession _session;

    /// <summary>绑定 Shell 展示模型和统一连接 Session。</summary>
    public ShellWindow(
        ShellViewModel viewModel,
        ControlCenterSession session)
    {
        InitializeComponent();
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        _session   = session ?? throw new ArgumentNullException(nameof(session));
        DataContext = viewModel;
        Closed += OnClosed;
    }

    private async void SaveAndConnect_Click(
        object sender,
        ExecutedRoutedEventArgs e)
    {
        if (_viewModel.CurrentPage is not SettingsPageViewModel settings)
        {
            return;
        }

        var TokenPasswordBox = FindNamedChild<PasswordBox>(
            ContentHost,
            "TokenPasswordBox");
        if (TokenPasswordBox is null)
        {
            MessageBox.Show(
                this,
                "无法读取设备令牌输入框，请重新打开设置页。",
                "连接失败",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        try
        {
            await _session.SaveAndConnectAsync(
                settings.MacBaseUrl,
                TokenPasswordBox.Password,
                CancellationToken.None);
            TokenPasswordBox.Clear();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                this,
                exception.Message,
                "连接失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        finally
        {
            e.Handled = true;
        }
    }

    private static T? FindNamedChild<T>(
        DependencyObject parent,
        string name)
        where T : FrameworkElement
    {
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is T element && string.Equals(element.Name, name, StringComparison.Ordinal))
            {
                return element;
            }
            var nested = FindNamedChild<T>(child, name);
            if (nested is not null)
            {
                return nested;
            }
        }
        return null;
    }

    private async void OnClosed(object? sender, EventArgs e)
    {
        Closed -= OnClosed;
        _viewModel.Dispose();
        try
        {
            await _session.DisposeAsync();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                $"退出时释放资源失败：{exception.Message}",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }
}
