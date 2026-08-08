using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>真实 STA WPF 验证 2.3.16.1 四个基础页完成 Measure/Arrange/UpdateLayout。</summary>
internal static class PlatformFoundationPagesWpfLayoutSmokeTests
{
    private static readonly string[] WorkerTaskTypes =
    [
        "system.diagnostic_snapshot",
        "system.noop",
    ];

    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                RunLayout();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static void RunLayout()
    {
        var now = DateTimeOffset.UtcNow;
        var project = new ProjectRecord(
            "project-layout", "平台项目", "automation", "PicotooPet", "Internal",
            null, "Active", now, now);
        var payload = JsonSerializer.SerializeToElement(new { purpose = "layout" });
        var step = new WorkflowStepRecord(
            "workflow-layout", "diagnostic", 0, "system.diagnostic_snapshot", null,
            Array.Empty<string>(), payload, "Ready", null, 0, 2, 30,
            now, now, null, null, null);
        var workflow = new WorkflowRecord(
            "workflow-layout", null, "平台诊断测试", "Ready", 100, 1,
            "layout-idempotency", now, now, null, null, null, new[] { step });
        var capability = new CapabilityRegistrationRecord(
            "mac-worker", "local.system.execution",
            WorkerTaskTypes, true,
            JsonSerializer.SerializeToElement(new { source = "worker-runtime" }),
            now, now);
        var health = new AutomationHealthResponse(
            new Dictionary<string, int> { ["Ready"] = 1 },
            new Dictionary<string, int> { ["Queued"] = 1 },
            new[] { capability }, 9, now);
        var fact = new AutomationDiagnosticFact(
            "workflow-layout", "diagnostic", "task-layout", "Failed",
            "FIXTURE_FAILURE", "结构化测试错误", "trace-layout", now);

        Measure(new ProjectsPage
        {
            DataContext = ProjectsPageViewModel.CreateForSmokeTest(new[] { project }),
        }, "Projects");
        Measure(new AutomationPage
        {
            DataContext = AutomationPageViewModel.CreateForSmokeTest(new[] { workflow }),
        }, "Automation");
        Measure(new HealthPage
        {
            DataContext = HealthPageViewModel.CreateForSmokeTest(health),
        }, "Health");
        Measure(new DiagnosticsPage
        {
            DataContext = DiagnosticsPageViewModel.CreateForSmokeTest(new[] { fact }),
        }, "Diagnostics");
    }

    private static void Measure(FrameworkElement page, string name)
    {
        page.Measure(new Size(1100, 760));
        page.Arrange(new Rect(0, 0, 1100, 760));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        SmokeAssert.True(page.IsMeasureValid, $"{name} Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, $"{name} Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, $"{name} Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, $"{name} Page 实际高度无效");
    }
}
