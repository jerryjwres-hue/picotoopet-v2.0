using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Shell 视图处理窗口生命周期、路由命令、页面故障隔离和 PasswordBox 密文转交。</summary>
public partial class ShellWindow : Window
{
    private readonly ShellViewModel _viewModel;
    private readonly ControlCenterSession _session;
    private readonly SafeFileLogger _logger;
    private bool _explicitExit;

    /// <summary>绑定 Shell 展示模型、统一连接 Session 和脱敏日志器。</summary>
    public ShellWindow(
        ShellViewModel viewModel,
        ControlCenterSession session,
        SafeFileLogger logger)
    {
        InitializeComponent();
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        _session   = session ?? throw new ArgumentNullException(nameof(session));
        _logger    = logger ?? throw new ArgumentNullException(nameof(logger));
        ReturnGatewayContext.SetGateway(
            this,
            new ControlCenterReturnGateway(_session));
        BrokerGatewayContext.SetGateway(
            this,
            new ControlCenterBrokerGateway(_session));
        ProviderGatewayContext.SetGateway(
            this,
            new ControlCenterProviderGateway(_session));
        ProviderReviewGatewayContext.SetGateway(
            this,
            new ControlCenterProviderReviewGateway(_session));
        DataContext = viewModel;
        _viewModel.PropertyChanged += OnShellViewModelPropertyChanged;
        SynchronizeSimpleModeChrome();
    }

    /// <summary>请求组合根按安全顺序释放资源并显式退出。</summary>
    public event EventHandler? ExitRequested;

    /// <summary>由托盘命令请求显式退出；窗口本身不直接释放共享资源。</summary>
    public void RequestExplicitExit() =>
        ExitRequested?.Invoke(this, EventArgs.Empty);

    /// <summary>允许 WPF 在资源释放后真正关闭窗口。</summary>
    public void AllowExplicitClose() =>
        _explicitExit = true;

    /// <summary>从托盘恢复、置前并激活主窗口。</summary>
    public void ShowFromTray()
    {
        if (!IsVisible)
        {
            Show();
        }
        if (WindowState == WindowState.Minimized)
        {
            WindowState = WindowState.Normal;
        }
        Activate();
    }

    /// <summary>普通关闭只隐藏到托盘；显式退出才允许窗口销毁。</summary>
    protected override void OnClosing(CancelEventArgs e)
    {
        if (!_explicitExit)
        {
            e.Cancel = true;
            Hide();
        }
        base.OnClosing(e);
    }

    /// <summary>窗口真正销毁时解除 ViewModel 订阅，避免残留视觉监听。</summary>
    protected override void OnClosed(EventArgs e)
    {
        _viewModel.PropertyChanged -= OnShellViewModelPropertyChanged;
        base.OnClosed(e);
    }

    /// <summary>直接由托盘或其他入口导航时，同步高级遮罩和五入口选中态。</summary>
    private void OnShellViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (!string.Equals(e.PropertyName, nameof(ShellViewModel.CurrentRoute), StringComparison.Ordinal)
            && !string.Equals(e.PropertyName, nameof(ShellViewModel.SelectedNavigationItem), StringComparison.Ordinal))
        {
            return;
        }

        if (Dispatcher.CheckAccess())
        {
            SynchronizeSimpleModeChrome();
            return;
        }

        _ = Dispatcher.InvokeAsync(SynchronizeSimpleModeChrome);
    }

    private void SynchronizeSimpleModeChrome()
    {
        var route = _viewModel.CurrentRoute;
        AdvancedHomePanel.Visibility = route == PicotooPet.Desktop.Navigation.NavigationRoute.AdvancedHome
            ? Visibility.Visible
            : Visibility.Collapsed;
        UpdateSimpleNavSelection(route);
    }

    /// <summary>记录被隔离的页面故障，并用安全说明页替换当前路由内容。</summary>
    private void ContentHost_NavigationFaulted(
        object sender,
        NavigationFaultEventArgs e)
    {
        var failedRoute = _viewModel.CurrentRoute;
        _logger.Error($"页面导航故障已隔离：{failedRoute}", e.Exception);
        _viewModel.ShowNavigationFailure(failedRoute);
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
}
