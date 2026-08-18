using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;
using PicotooPet.Desktop.Views.Controls;
using WpfApplication = System.Windows.Application;
using WpfMessageBox = System.Windows.MessageBox;

namespace PicotooPet.Desktop;

/// <summary>桌面应用组合根；不使用隐藏的全局 Service Locator。</summary>
public partial class App : WpfApplication, IDisposable
{
    private const double MinimumOperatorFontSize = 12.0;

    private Mutex? _singleInstanceMutex;
    private ControlCenterSession? _session;
    private ShellViewModel? _shellViewModel;
    private ShellWindow? _shellWindow;
    private WindowsTrayService? _trayService;
    private SafeFileLogger? _logger;
    private bool _ownsSingleInstance;
    private bool _runtimeDisposing;
    private bool _readabilityHandlerRegistered;

    /// <summary>只创建常规桌面组合根；Broker 子模式已在 Program 中提前分流。</summary>
    protected override void OnStartup(StartupEventArgs e)
    {
        RegisterReadabilityFloor();
        if (e.Args.Any(argument =>
                string.Equals(argument, "--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            base.OnStartup(e);
            Shutdown(AppSelfTest.Run(e.Args));
            return;
        }

        var createdNew = false;
        _singleInstanceMutex = new Mutex(
            initiallyOwned: true,
            name: @"Local\PicotooPetV2.Desktop.SingleInstance",
            createdNew: out createdNew);
        _ownsSingleInstance = createdNew;
        if (!createdNew)
        {
            WpfMessageBox.Show(
                "Picotoo Pet AI 已经在运行。",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            Shutdown();
            return;
        }

        base.OnStartup(e);
        var dataRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PicotooPetV2",
            "Desktop");
        var logger          = new SafeFileLogger(Path.Combine(dataRoot, "logs", "desktop.log"));
        var tokenStore      = new CredentialManagerTokenStore();
        var settings        = new DesktopSettingsStore(Path.Combine(dataRoot, "settings.json"));
        var dispatcher      = new WpfUiDispatcher(Current.Dispatcher);
        var connectionStore = new ConnectionStateStore();
        var capabilityStore = new CapabilityStateStore();
        var taskStore       = new TaskStateStore();

        _logger = logger;
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        _session = new ControlCenterSession(
            tokenStore,
            settings,
            logger,
            connectionStore,
            capabilityStore,
            taskStore);
        _shellViewModel = new ShellViewModel(_session, dispatcher);
        _shellWindow    = new ShellWindow(_shellViewModel, _session, logger);
        _trayService    = new WindowsTrayService();

        _trayService.OpenRequested += OnTrayOpenRequested;
        _trayService.PendingApprovalsRequested += OnPendingApprovalsRequested;
        _trayService.ExitRequested += OnTrayExitRequested;
        _shellWindow.ExitRequested += OnShellExitRequested;

        MainWindow = _shellWindow;
        _shellWindow.Show();
        _ = InitializeViewModelAsync(_session, _shellWindow, logger);
    }

    /// <summary>
    /// 旧页面存在 8–11 DIP 的局部硬编码。统一在控件加载时把正常操作界面夹到 12 DIP，
    /// 同时排除 AssistantPetPanel 与透明 FloatingPetWindow，避免改变桌宠视觉比例。
    /// </summary>
    private void RegisterReadabilityFloor()
    {
        if (_readabilityHandlerRegistered)
        {
            return;
        }
        _readabilityHandlerRegistered = true;
        EventManager.RegisterClassHandler(
            typeof(TextBlock),
            FrameworkElement.LoadedEvent,
            new RoutedEventHandler(OnOperatorTextLoaded));
    }

    private static void OnOperatorTextLoaded(object sender, RoutedEventArgs e)
    {
        if (sender is not TextBlock text
            || text.FontSize >= MinimumOperatorFontSize
            || IsPetSurface(text))
        {
            return;
        }
        text.FontSize = MinimumOperatorFontSize;
        TextOptions.SetTextFormattingMode(text, TextFormattingMode.Display);
        TextOptions.SetTextRenderingMode(text, TextRenderingMode.ClearType);
    }

    private static bool IsPetSurface(DependencyObject element)
    {
        DependencyObject? current = element;
        while (current is not null)
        {
            if (current is AssistantPetPanel or FloatingPetWindow)
            {
                return true;
            }
            current = VisualTreeHelper.GetParent(current);
        }
        return false;
    }

    /// <summary>同步固化逃出页面故障边界的 WPF 证据，但仍不吞掉未知进程级故障。</summary>
    private void OnDispatcherUnhandledException(
        object sender,
        DispatcherUnhandledExceptionEventArgs e)
    {
        _logger?.EmergencyError("WPF 未处理异常", e.Exception);
    }

    private static async Task InitializeViewModelAsync(
        ControlCenterSession session,
        Window owner,
        SafeFileLogger logger)
    {
        try
        {
            await session.InitializeAsync(CancellationToken.None);
        }
        catch (Exception exception)
        {
            logger.Error("Control Center 初始化失败", exception);
            await owner.Dispatcher.InvokeAsync(() => WpfMessageBox.Show(
                owner,
                "初始化没有完成。你仍可在设置页重新配对；详细信息已写入本地脱敏日志。",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Warning));
        }
    }

    private void OnTrayOpenRequested(object? sender, EventArgs e) =>
        RunOnUiThread(() => _shellWindow?.ShowFromTray());

    private void OnPendingApprovalsRequested(object? sender, EventArgs e) =>
        RunOnUiThread(() =>
        {
            _shellWindow?.ShowFromTray();
            _shellViewModel?.Navigate(NavigationRoute.Approvals);
        });

    private void OnTrayExitRequested(object? sender, EventArgs e) =>
        RunOnUiThread(() => _shellWindow?.RequestExplicitExit());

    private async void OnShellExitRequested(object? sender, EventArgs e)
    {
        try
        {
            await DisposeRuntimeAsync();
        }
        catch (Exception exception)
        {
            _logger?.Error("退出时释放资源失败", exception);
            WpfMessageBox.Show(
                _shellWindow,
                "退出时有资源未能正常释放。程序仍会安全退出；详细信息已写入本地脱敏日志。",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
        finally
        {
            _shellWindow?.AllowExplicitClose();
            Shutdown();
        }
    }

    private void RunOnUiThread(Action action)
    {
        if (Dispatcher.CheckAccess())
        {
            action();
            return;
        }
        _ = Dispatcher.InvokeAsync(action);
    }

    /// <summary>按 ViewModel、Session、托盘的顺序解除订阅并释放所有运行时资源。</summary>
    private async Task DisposeRuntimeAsync()
    {
        if (_runtimeDisposing)
        {
            return;
        }
        _runtimeDisposing = true;

        DispatcherUnhandledException -= OnDispatcherUnhandledException;
        if (_shellWindow is not null)
        {
            _shellWindow.ExitRequested -= OnShellExitRequested;
        }
        if (_trayService is not null)
        {
            _trayService.OpenRequested -= OnTrayOpenRequested;
            _trayService.PendingApprovalsRequested -= OnPendingApprovalsRequested;
            _trayService.ExitRequested -= OnTrayExitRequested;
        }

        _shellViewModel?.Dispose();
        _shellViewModel = null;

        if (_session is not null)
        {
            await _session.DisposeAsync();
            _session = null;
        }
        _logger = null;
        if (_trayService is not null)
        {
            _trayService.Dispose();
            _trayService = null;
        }
    }

    /// <summary>显式释放应用持有的单实例互斥锁。</summary>
    public void Dispose()
    {
        DisposeSingleInstanceMutex();
        GC.SuppressFinalize(this);
    }

    /// <summary>进程退出时释放命名互斥锁，允许下一次启动接管。</summary>
    protected override void OnExit(ExitEventArgs e)
    {
        Dispose();
        base.OnExit(e);
    }

    /// <summary>幂等释放互斥锁；重复调用不会再次释放所有权。</summary>
    private void DisposeSingleInstanceMutex()
    {
        var mutex = _singleInstanceMutex;
        if (mutex is null)
        {
            return;
        }

        if (_ownsSingleInstance)
        {
            try
            {
                mutex.ReleaseMutex();
            }
            catch (ApplicationException)
            {
                // 退出阶段即使所有权已被系统回收，也不得阻止进程结束。
            }
        }

        mutex.Dispose();
        _singleInstanceMutex = null;
        _ownsSingleInstance  = false;
    }
}
