using System.Windows;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop;

/// <summary>桌面应用组合根；不使用隐藏的全局 Service Locator。</summary>
public partial class App : Application
{
    private Mutex? _singleInstanceMutex;
    private bool _ownsSingleInstance;

    /// <summary>创建单实例保护、日志、安全令牌存储和主窗口。</summary>
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
        var logger      = new SafeFileLogger(Path.Combine(dataRoot, "logs", "desktop.log"));
        var tokenStore  = new CredentialManagerTokenStore();
        var settings    = new DesktopSettingsStore(Path.Combine(dataRoot, "settings.json"));
        var dispatcher  = new WpfUiDispatcher(Current.Dispatcher);
        var viewModel   = new MainWindowViewModel(tokenStore, settings, dispatcher, logger);
        var window      = new MainWindow(viewModel);
        MainWindow      = window;
        window.Show();
        _ = InitializeViewModelAsync(viewModel, window, logger);
    }

    private static async Task InitializeViewModelAsync(
        MainWindowViewModel viewModel,
        Window owner,
        SafeFileLogger logger)
    {
        try
        {
            await viewModel.InitializeAsync(CancellationToken.None);
        }
        catch (Exception exception)
        {
            logger.Error("桌面初始化失败", exception);
            await owner.Dispatcher.InvokeAsync(() => MessageBox.Show(
                owner,
                $"初始化失败：{exception.Message}\n\n详细日志位于本地应用数据目录。",
                "Picotoo Pet AI",
                MessageBoxButton.OK,
                MessageBoxImage.Warning));
        }
    }

    /// <summary>进程退出时释放命名互斥锁，允许下一次启动接管。</summary>
    protected override void OnExit(ExitEventArgs e)
    {
        if (_ownsSingleInstance && _singleInstanceMutex is not null)
        {
            try
            {
                _singleInstanceMutex.ReleaseMutex();
            }
            catch (ApplicationException)
            {
                // 退出阶段即使所有权已被系统回收，也不得阻止进程结束。
            }
        }
        _singleInstanceMutex?.Dispose();
        _singleInstanceMutex = null;
        _ownsSingleInstance  = false;
        base.OnExit(e);
    }
}
