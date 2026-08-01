using System.IO;
using System.Windows;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop;

/// <summary>桌面应用组合根；不使用隐藏的全局 Service Locator。</summary>
public partial class App : Application, IDisposable
{
    private Mutex? _singleInstanceMutex;
    private bool _ownsSingleInstance;

    /// <summary>创建单实例保护、日志、安全令牌存储、状态仓库和 Control Center Shell。</summary>
    protected override void OnStartup(StartupEventArgs e)
    {
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
            MessageBox.Show(
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
        var session = new ControlCenterSession(
            tokenStore,
            settings,
            logger,
            connectionStore,
            capabilityStore,
            taskStore);
        var viewModel = new ShellViewModel(session, dispatcher);
        var window    = new ShellWindow(viewModel, session);
        MainWindow = window;
        window.Show();
        _ = InitializeSessionAsync(session, window, logger);
    }

    private static async Task InitializeSessionAsync(
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
            await owner.Dispatcher.InvokeAsync(() => MessageBox.Show(
                owner,
                $"初始化失败：{exception.Message}\n\n你仍可在设置页重新配对；详细日志位于本地应用数据目录。",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Warning));
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
