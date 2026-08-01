using System.IO;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

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
            ["schema_version"] = "2.3.0",
            ["generated_at"]   = DateTimeOffset.UtcNow,
            ["status"]         = "running",
            ["checks"]         = new Dictionary<string, string>(StringComparer.Ordinal),
            ["error"]          = null,
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
            if (shell.NavigationItems.Count != 10)
            {
                throw new InvalidOperationException("Control Center 一级导航数量自检失败。");
            }
            if (!shell.NavigationItems.Single(
                    item => item.Route == NavigationRoute.TaskCenter).IsAvailable)
            {
                throw new InvalidOperationException("Legacy 2.2 任务中心兼容自检失败。");
            }
            if (shell.NavigationItems.Single(
                    item => item.Route == NavigationRoute.CloudDevelopment).IsAvailable)
            {
                throw new InvalidOperationException("云端开发能力关闭自检失败。");
            }
            shell.Navigate(NavigationRoute.Settings);
            if (shell.CurrentPage is not SettingsPageViewModel)
            {
                throw new InvalidOperationException("Control Center 设置页路由自检失败。");
            }
            checks["control_center_shell"] = "pass";

            Directory.Delete(tempRoot, recursive: true);
            checks["filesystem_cleanup"] = "pass";
            report["status"] = "pass";
            WriteReport(outputPath, report);
            Console.WriteLine("PHASE2_DESKTOP_SELF_TEST=PASS");
            Console.WriteLine("PHASE23_CONTROL_CENTER_SELF_TEST=PASS");
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
            return 1;
        }
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
