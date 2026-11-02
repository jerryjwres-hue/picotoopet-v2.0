using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>从真实 Superpower Shell 按钮抵达同一个生产/审片面板；所有测试会话断线，零 GPU。</summary>
internal static class ProductionShellEntryWpfSmokeTests
{
    public static void Run()
    {
        Exception? error = null;
        var thread = new Thread(() =>
        {
            try { VerifyRealEntryOnSta(); }
            catch (Exception ex) { error = ex; }
        });
        // Test bound       : a modal dialog or off-thread WPF failure must not hang hosted CI.
        thread.IsBackground = true;
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        if (!thread.Join(TimeSpan.FromSeconds(20)))
        {
            throw new TimeoutException("真实高级审片按钮的 STA 测试超时；可能存在阻塞对话框或 UI Dispatcher 死锁。");
        }
        if (error is not null) ExceptionDispatchInfo.Capture(error).Throw();
    }

    private static void VerifyRealEntryOnSta()
    {
        // 真实应用资源  : 仅加载 WPF XAML，绝不启动 App.OnStartup / Background Worker。
        // 离线会话      : Core 不可连接；即使面板触发 Refresh，也不产生 GPU 作业。
        var app = Application.Current as App ?? new App();
        app.InitializeComponent();
        var root = Path.Combine(Path.GetTempPath(), "picotoo-shell-entry-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var logger = new SafeFileLogger(Path.Combine(root, "smoke.log"));
        var session = new ControlCenterSession(
            new CredentialManagerTokenStore("PicotooPetV2/SmokeOnly-NeverRead"),
            new DesktopSettingsStore(Path.Combine(root, "smoke-settings.json")),
            logger,
            new ConnectionStateStore(),
            new CapabilityStateStore(),
            new TaskStateStore());
        using var viewModel = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);
        Window? shellWindow = null;
        try
        {
            var shell = new ShellWindow(viewModel, session, logger);
            shellWindow = shell;
            viewModel.Navigate(NavigationRoute.AdvancedHome);
            shell.Width = 1280;
            shell.Height = 840;
            shell.Measure(new Size(1280, 840));
            shell.Arrange(new Rect(0, 0, 1280, 840));
            shell.UpdateLayout();
            shell.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

            // 可达性入口    : 必须是实际 ShellWindow 的具名按钮，非孤立面板测试替身。
            var entry = shell.FindName("OpenProductionPanelButton") as Button;
            SmokeAssert.True(entry is not null && entry.IsEnabled, "真实高级 Shell 缺少可点击的生产审片入口");
            SmokeAssert.True(entry!.Content?.ToString() == "本地生产与审片", "高级生产审片按钮标题不一致");
            entry.RaiseEvent(new RoutedEventArgs(Button.ClickEvent, entry));
            shell.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

            // 真实面板      : 点击必须打开既有 ProductionPanel，不允许构造替代生产执行器。
            var panels = Application.Current.Windows.Cast<Window>()
                .Where(w => ReferenceEquals(w.Owner, shell) && w.Content is ProductionPanel)
                .ToArray();
            SmokeAssert.True(panels.Length == 1, "真实高级按钮未打开唯一的 ProductionPanel");
            var panel = (ProductionPanel)panels[0].Content;
            SmokeAssert.True(panel.DataContext is ProductionPanelViewModel,
                "审片窗口没有连接生产 ViewModel");
            SmokeAssert.True(FindVisual<Button>(panel)
                .Any(button => button.Content?.ToString()?.Contains("视觉证据", StringComparison.Ordinal) == true),
                "真实生产面板未显示视觉证据按钮");

            // 重复点击      : 必须激活原窗口而非创建新的生产服务及 Window。
            entry.RaiseEvent(new RoutedEventArgs(Button.ClickEvent, entry));
            SmokeAssert.True(Application.Current.Windows.Cast<Window>()
                .Count(w => ReferenceEquals(w.Owner, shell) && w.Content is ProductionPanel) == 1,
                "重复点击错误创建第二套生产面板");
            panels[0].Close();
            shell.AllowExplicitClose();
            shell.Close();
            shellWindow = null;
            Console.WriteLine("REAL_SUPERPOWER_ADVANCED_REVIEW_BUTTON=PASS; UNIQUE_PANEL=PASS; GPU_POST=0");
        }
        finally
        {
            // 安全清理      : 不触碰用户 Credential Manager、生产 Mac/Comfy/设备。
            if (shellWindow is ShellWindow pending) { pending.AllowExplicitClose(); pending.Close(); }
            session.DisposeAsync().AsTask().GetAwaiter().GetResult();
            logger.DisposeAsync().AsTask().GetAwaiter().GetResult();
            try { Directory.Delete(root, recursive: true); } catch (IOException) { }
        }
    }

    private static IEnumerable<T> FindVisual<T>(DependencyObject root) where T : DependencyObject
    {
        foreach (var childIndex in Enumerable.Range(0, VisualTreeHelper.GetChildrenCount(root)))
        {
            var child = VisualTreeHelper.GetChild(root, childIndex);
            if (child is T match) yield return match;
            foreach (var nested in FindVisual<T>(child)) yield return nested;
        }
    }
}
