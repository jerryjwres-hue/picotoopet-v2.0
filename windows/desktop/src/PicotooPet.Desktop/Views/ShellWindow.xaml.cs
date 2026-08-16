using System.ComponentModel;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Services;
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
        InsertDeletedNavigationButton();
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

        // DataContext     : PetPresentation 和其余 Shell 状态共用同一只读 VM 更新链。
        DataContext = viewModel;

        // Floating pet   : presentation-only request; no Session/task/approval command is added.
        AssistantPet.FloatRequested += OnAssistantPetFloatRequested;
    }

    /// <summary>在现有硬编码简单导航中插入第六项“已删除”，保持原视觉样式和顺序。</summary>
    private void InsertDeletedNavigationButton()
    {
        if (SimpleCompletedButton.Parent is not Panel panel)
        {
            throw new InvalidOperationException("简单导航容器不可用。");
        }
        var button = new Button
        {
            Content = "已删除",
            Tag = "↶",
            Style = (Style)FindResource("SimpleNavButtonStyle"),
        };
        AutomationProperties.SetName(button, "已删除");
        button.Click += SimpleDeleted_Click;
        var completedIndex = panel.Children.IndexOf(SimpleCompletedButton);
        panel.Children.Insert(completedIndex + 1, button);
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

    /// <summary>窗口真正销毁时解除 UI 事件，并关闭同进程悬浮桌宠。</summary>
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

    /// <summary>记录被隔离的页面故障，并用安全说明页替换当前路由内容。</summary>
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
            // Failure isolation : a floating-pet rendering error must not destabilize the main Shell.
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
