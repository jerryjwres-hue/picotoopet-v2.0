using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.DevBroker;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.Versioning;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Services;

/// <summary>Windows CI 和发布包使用的无界面启动自检。</summary>
internal static class AppSelfTest
{
    private static readonly JsonSerializerOptions ReportJsonOptions = new()
    {
        WriteIndented = true,
    };

    /// <summary>验证应用组合根可加载、日志可安全写入且 Control Center Shell 可构造。</summary>
    public static int Run(string[] args)
    {
        var outputPath = GetArgumentValue(args, "--self-test-output")
            ?? Path.Combine(
                Path.GetTempPath(),
                $"picotoo-desktop-self-test-{Guid.NewGuid():N}.json");
        var report = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["schema_version"]          = "2.3.0",
            ["product_version"]         = ProductVersionInfo.Current,
            ["window_title"]            = ProductVersionInfo.WindowTitle,
            ["control_center_subtitle"] = ProductVersionInfo.ControlCenterSubtitle,
            ["generated_at"]            = DateTimeOffset.UtcNow,
            ["status"]                  = "running",
            ["checks"]                  = new Dictionary<string, string>(StringComparer.Ordinal),
            ["error"]                   = null,
        };

        try
        {
            var checks = (Dictionary<string, string>)report["checks"]!;
            var tempRoot = Path.Combine(
                Path.GetTempPath(),
                "PicotooPetV2",
                "desktop-self-test",
                Guid.NewGuid().ToString("N"));
            var logPath = Path.Combine(tempRoot, "self-test.log");
            Directory.CreateDirectory(tempRoot);

            var logger = new SafeFileLogger(logPath, capacity: 128);
            logger.Info("self-test Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ");
            logger.DisposeAsync().AsTask().GetAwaiter().GetResult();
            var logText = File.ReadAllText(logPath);
            if (!logText.Contains("[REDACTED]", StringComparison.Ordinal))
            {
                throw new InvalidOperationException("安全日志脱敏自检失败。");
            }
            checks["safe_logger"] = "pass";

            var options = MacCoreClientOptions.CreateDefault(
                new Uri("http://127.0.0.1:8766", UriKind.Absolute),
                "self-test-token");
            if (options.BaseUri.Port != 8766 || options.RequestTimeout <= TimeSpan.Zero)
            {
                throw new InvalidOperationException("Mac Core 客户端参数自检失败。");
            }
            checks["client_options"] = "pass";

            using var shell = ShellViewModel.CreateForSmokeTest(
                ControlCenterCapabilities.Legacy22);
            if (shell.WindowTitle != ProductVersionInfo.WindowTitle
                || shell.ControlCenterSubtitle != ProductVersionInfo.ControlCenterSubtitle)
            {
                throw new InvalidOperationException("Control Center 产品版本文案自检失败。");
            }
            checks["product_version_surfaces"] = "pass";

            if (shell.NavigationItems.Count != 10)
            {
                throw new InvalidOperationException("Control Center 一级导航数量自检失败。");
            }
            if (!shell.NavigationItems.Single(
                    item => item.Route == NavigationRoute.TaskCenter).IsAvailable)
            {
                throw new InvalidOperationException("Legacy 2.2 任务中心兼容自检失败。");
            }
            if (!shell.NavigationItems.Single(
                    item => item.Route == NavigationRoute.CloudDevelopment).IsAvailable)
            {
                throw new InvalidOperationException("云端开发 Phase 10A 页面可用性自检失败。");
            }

            shell.Navigate(NavigationRoute.CloudDevelopment);
            if (shell.CurrentPage is not CloudDevelopmentPageViewModel cloudDevelopment
                || cloudDevelopment.ContractVersion != "1.0.0"
                || cloudDevelopment.ProviderConfigured
                || cloudDevelopment.TemplateOptions.Count != 1
                || !cloudDevelopment.CurrentDelivery.Contains(
                    "Phase 10A",
                    StringComparison.Ordinal))
            {
                throw new InvalidOperationException("云端开发 Phase 10A 安全边界自检失败。");
            }
            checks["cloud_development_phase10a"] = "pass";

            VerifyCloudDevelopmentContentRendering(cloudDevelopment);
            checks["cloud_development_rendering"]             = "pass";
            checks["cloud_development_phase10b_return_panel"] = "pass";
            checks["cloud_development_phase10b_broker_panel"] = "pass";

            VerifyPublishedBrokerChildProcess();
            checks["cloud_development_phase10b_broker_process"] = "pass";

            shell.Navigate(NavigationRoute.TaskCenter);
            if (shell.CurrentPage is not TaskCenterPageViewModel taskCenter
                || taskCenter.WorkerStatusText != "执行器未部署")
            {
                throw new InvalidOperationException("任务中心 Worker 解释自检失败。");
            }
            checks["task_center_policy"] = "pass";

            VerifyTaskCenterContentRendering(taskCenter);
            checks["task_center_rendering"] = "pass";

            shell.Navigate(NavigationRoute.Settings);
            if (shell.CurrentPage is not SettingsPageViewModel)
            {
                throw new InvalidOperationException("Control Center 设置页路由自检失败。");
            }
            checks["control_center_shell"] = "pass";

            var worker = WorkerSnapshot.NotDeployed;
            if (worker.Available || worker.State != "not_deployed")
            {
                throw new InvalidOperationException("Worker 保守降级自检失败。");
            }
            checks["worker_fallback"] = "pass";

            Directory.Delete(tempRoot, recursive: true);
            checks["filesystem_cleanup"] = "pass";
            report["status"] = "pass";
            WriteReport(outputPath, report);
            Console.WriteLine("PHASE2_DESKTOP_SELF_TEST=PASS");
            Console.WriteLine("PHASE23_CONTROL_CENTER_SELF_TEST=PASS");
            Console.WriteLine("PHASE23_TASK_CENTER_SELF_TEST=PASS");
            Console.WriteLine("PHASE23_PRODUCT_VERSION_SELF_TEST=PASS");
            Console.WriteLine("PHASE10A_HANDOFF_SELF_TEST=PASS");
            Console.WriteLine("PHASE10B_RETURN_SELF_TEST=PASS");
            Console.WriteLine("PHASE10B_BROKER_SELF_TEST=PASS");
            Console.WriteLine("PHASE10B_BROKER_PROCESS_SELF_TEST=PASS");
            return 0;
        }
        catch (Exception exception)
        {
            report["status"] = "fail";
            report["error"]  = $"{exception.GetType().Name}: {exception.Message}";
            WriteReport(outputPath, report);
            Console.Error.WriteLine(
                $"PHASE2_DESKTOP_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE23_CONTROL_CENTER_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE23_TASK_CENTER_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE23_PRODUCT_VERSION_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE10A_HANDOFF_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE10B_RETURN_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE10B_BROKER_SELF_TEST=FAIL | {exception.Message}");
            Console.Error.WriteLine(
                $"PHASE10B_BROKER_PROCESS_SELF_TEST=FAIL | {exception.Message}");
            return 1;
        }
    }

    /// <summary>使用当前正式 WinExe 验证隐藏子进程、固定沙盒文件和 Return 合同闭环。</summary>
    private static void VerifyPublishedBrokerChildProcess()
    {
        var now           = DateTimeOffset.UtcNow;
        var sessionId     = Guid.NewGuid().ToString("D");
        var handoffId     = Guid.NewGuid().ToString("D");
        var requestDigest = new string('a', 64);
        var packageDigest = new string('b', 64);
        var baseCommit    = new string('c', 40);
        var record = new BrokerSessionRecord(
            sessionId,
            handoffId,
            "reserved",
            "local-mock-dev-broker",
            30,
            requestDigest,
            packageDigest,
            null,
            0,
            null,
            null,
            now,
            now,
            null,
            "只运行固定内置 Mock Provider。");
        var session = new BrokerSessionCreateResult(record, new string('d', 64));
        var handoff = new HandoffRecord(
            handoffId,
            "picotoopet-repository-maintenance",
            "PicotooPet 仓库维护",
            "发布 EXE Broker 子进程自检",
            "验证正式 WinExe 可以启动固定子模式并从沙盒文件读取 Return。",
            "approved",
            "none",
            false,
            "https://github.com/jerryjwres-hue/picotoopet-v2.0",
            "main",
            baseCommit,
            "internal",
            1,
            1,
            ["broker-self-test"],
            "1 turn · 30 秒 · 无网络",
            requestDigest,
            packageDigest,
            null,
            now,
            now,
            now.AddMinutes(5),
            ["fixed-local-sandbox"]);

        var envelope = DevBrokerProcessRunner.RunAsync(
                session,
                handoff,
                CancellationToken.None)
            .GetAwaiter()
            .GetResult();
        if (envelope.SessionId != sessionId
            || envelope.HandoffId != handoffId
            || envelope.Provider != "local-mock-dev-broker"
            || envelope.Files.Count != 10
            || !envelope.Files.Any(file =>
                file.Name == "changes/docs/mock-provider-proof.txt"))
        {
            throw new InvalidOperationException(
                "发布 EXE 的 Mock Broker 子进程 Return 合同自检失败。");
        }
    }

    /// <summary>验证发布进程中的 Phase 10A/10B-A/10B-B DataTemplate 可生成原生页面。</summary>
    private static void VerifyCloudDevelopmentContentRendering(
        CloudDevelopmentPageViewModel cloudDevelopment)
    {
        var host = new NavigationContentHost
        {
            Content = cloudDevelopment,
        };
        var root = new System.Windows.Controls.Border
        {
            Width  = 1100,
            Height = 1320,
            Child  = host,
        };

        root.Measure(new System.Windows.Size(1100, 1320));
        root.Arrange(new System.Windows.Rect(0, 0, 1100, 1320));
        root.UpdateLayout();
        root.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        root.UpdateLayout();

        var page = FindVisualDescendant<CloudDevelopmentPage>(host);
        if (page is null)
        {
            throw new InvalidOperationException(
                "发布 EXE 未通过生产 DataTemplate 渲染 CloudDevelopmentPage。");
        }
        if (page.ActualWidth <= 0 || page.ActualHeight <= 0)
        {
            throw new InvalidOperationException(
                "发布 EXE 中的 CloudDevelopmentPage 没有可见布局尺寸。");
        }
        if (FindVisualDescendants<System.Windows.Controls.Button>(page).Count < 8
            || FindVisualDescendants<System.Windows.Controls.TextBox>(page).Count < 2
            || FindVisualDescendant<ReturnValidationPanel>(page) is null
            || FindVisualDescendant<BrokerSessionPanel>(page) is null)
        {
            throw new InvalidOperationException(
                "发布 EXE 中的 Phase 10A、Return 或 Mock Dev Broker 原生控件不完整。");
        }
        if (FindVisualDescendants<System.Windows.Controls.PasswordBox>(page).Count != 0
            || FindVisualDescendants<System.Windows.Controls.WebBrowser>(page).Count != 0)
        {
            throw new InvalidOperationException(
                "发布 EXE 中的云端开发页面包含凭据或浏览器控件。");
        }
    }

    /// <summary>在当前发布进程中验证生产 DataTemplate 会生成可见任务中心页面。</summary>
    private static void VerifyTaskCenterContentRendering(
        TaskCenterPageViewModel taskCenter)
    {
        var host = new NavigationContentHost
        {
            Content = taskCenter,
        };
        var root = new System.Windows.Controls.Border
        {
            Width  = 960,
            Height = 680,
            Child  = host,
        };

        root.Measure(new System.Windows.Size(960, 680));
        root.Arrange(new System.Windows.Rect(0, 0, 960, 680));
        root.UpdateLayout();
        root.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        root.UpdateLayout();

        var page = FindVisualDescendant<TaskCenterPage>(host);
        if (page is null)
        {
            throw new InvalidOperationException(
                "发布 EXE 未通过生产 DataTemplate 渲染 TaskCenterPage。");
        }
        if (page.ActualWidth <= 0 || page.ActualHeight <= 0)
        {
            throw new InvalidOperationException(
                "发布 EXE 中的 TaskCenterPage 没有可见布局尺寸。");
        }
    }

    private static T? FindVisualDescendant<T>(DependencyObject parent)
        where T : DependencyObject =>
        FindVisualDescendants<T>(parent).FirstOrDefault();

    private static List<T> FindVisualDescendants<T>(DependencyObject parent)
        where T : DependencyObject
    {
        var matches    = new List<T>();
        var childCount = VisualTreeHelper.GetChildrenCount(parent);
        for (var index = 0; index < childCount; index++)
        {
            var child = VisualTreeHelper.GetChild(parent, index);
            if (child is T match)
            {
                matches.Add(match);
            }
            matches.AddRange(FindVisualDescendants<T>(child));
        }
        return matches;
    }

    private static string? GetArgumentValue(string[] args, string name)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }
        return null;
    }

    private static void WriteReport(string path, object report)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
        File.WriteAllText(
            path,
            JsonSerializer.Serialize(report, ReportJsonOptions));
    }
}
