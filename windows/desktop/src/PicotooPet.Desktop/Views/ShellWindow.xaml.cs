using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Versioning;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Views;

/// <summary>Shell 视图处理窗口生命周期、路由命令、页面故障隔离、桌宠窗口和 PasswordBox 密文转交。</summary>
public partial class ShellWindow : Window
{
    private readonly ShellViewModel _viewModel;
    private readonly ControlCenterSession _session;
    private readonly SafeFileLogger _logger;
    private FloatingPetWindow? _floatingPetWindow;
    private bool _explicitExit;

    /// <summary>绑定 Shell 展示模型、统一连接 Session、桌宠 UI 和脱敏日志器。</summary>
    public ShellWindow(
        ShellViewModel viewModel,
        ControlCenterSession session,
        SafeFileLogger logger)
    {
        InitializeComponent();
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        _session   = session ?? throw new ArgumentNullException(nameof(session));
        _logger    = logger ?? throw new ArgumentNullException(nameof(logger));

        ReturnGatewayContext.SetGateway(this, new ControlCenterReturnGateway(_session));
        BrokerGatewayContext.SetGateway(this, new ControlCenterBrokerGateway(_session));
        ProviderGatewayContext.SetGateway(this, new ControlCenterProviderGateway(_session));
        ProviderReviewGatewayContext.SetGateway(this, new ControlCenterProviderReviewGateway(_session));
        CodingEscalationDecisionGatewayContext.SetGateway(this, _session);
        TaskDetailGatewayContext.SetGateway(this, new ControlCenterTaskDetailGateway(_session));

        DataContext = viewModel;
        // 保留既有 XAML / 导航 / 茅台宿主，仅把历史品牌文案统一成当前产品名。
        ApplyProductIdentity(this);

        // 茅台表面仍由独立组件负责；Shell 只保留既有浮窗请求边界。
        AssistantPet.FloatRequested += OnAssistantPetFloatRequested;
    }

    /// <summary>请求组合根按安全顺序释放资源并显式退出。</summary>
    public event EventHandler? ExitRequested;

    public void RequestExplicitExit() => ExitRequested?.Invoke(this, EventArgs.Empty);

    public void AllowExplicitClose() => _explicitExit = true;

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

    protected override void OnClosing(CancelEventArgs e)
    {
        if (!_explicitExit)
        {
            e.Cancel = true;
            Hide();
        }
        base.OnClosing(e);
    }

    protected override void OnClosed(EventArgs e)
    {
        AssistantPet.FloatRequested -= OnAssistantPetFloatRequested;

        if (_floatingPetWindow is not null)
        {
            _floatingPetWindow.Closed -= FloatingPetWindow_Closed;
            _floatingPetWindow.Close();
            _floatingPetWindow = null;
        }

        base.OnClosed(e);
    }

    private void ContentHost_NavigationFaulted(
        object sender,
        NavigationFaultEventArgs e)
    {
        var failedRoute = _viewModel.CurrentRoute;
        _logger.Error($"页面导航故障已隔离：{failedRoute}", e.Exception);
        _viewModel.ShowNavigationFailure(failedRoute);
    }

    private void OnAssistantPetFloatRequested(object? sender, EventArgs e)
    {
        if (_floatingPetWindow is { IsVisible: true })
        {
            _floatingPetWindow.Activate();
            return;
        }

        try
        {
            var window = new FloatingPetWindow(_viewModel);
            window.Closed += FloatingPetWindow_Closed;
            _floatingPetWindow = window;
            window.Show();
            window.Activate();
        }
        catch (Exception exception)
        {
            _logger.Error("悬浮桌宠打开失败，主窗口继续运行。", exception);
            _floatingPetWindow = null;
        }
    }

    private void FloatingPetWindow_Closed(object? sender, EventArgs e)
    {
        if (sender is FloatingPetWindow window)
        {
            window.Closed -= FloatingPetWindow_Closed;
        }
        _floatingPetWindow = null;
    }

    private async void SaveAndConnect_Click(
        object sender,
        ExecutedRoutedEventArgs e)
    {
        if (_viewModel.CurrentPage is not SettingsPageViewModel settings)
        {
            return;
        }

        var TokenPasswordBox = FindNamedChild<PasswordBox>(ContentHost, "TokenPasswordBox");
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
            _logger.Error("连接 Mac Core 失败", exception);
            MessageBox.Show(
                this,
                "连接没有完成。请检查 Mac 地址和设备令牌后重试；详细信息已写入本地脱敏日志。",
                "连接失败",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        finally
        {
            e.Handled = true;
        }
    }

    /// <summary>只替换历史硬编码品牌 TextBlock；不重建或重排现有可视树。</summary>
    private static void ApplyProductIdentity(DependencyObject parent)
    {
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is TextBlock textBlock
                && string.Equals(textBlock.Text, "Picotoo Pet AI", StringComparison.Ordinal))
            {
                textBlock.Text = ProductVersionInfo.ProductName;
            }
            ApplyProductIdentity(child);
        }
    }

    private static T? FindNamedChild<T>(DependencyObject parent, string name)
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
