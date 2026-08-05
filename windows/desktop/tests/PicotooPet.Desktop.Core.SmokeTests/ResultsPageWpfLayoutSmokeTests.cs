using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 页面上验证结果中心列表和只读预览绑定完成布局。</summary>
internal static class ResultsPageWpfLayoutSmokeTests
{
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
        var timestamp = new DateTimeOffset(2026, 8, 5, 1, 0, 0, TimeSpan.Zero);
        var task = new TaskRecord(
            TaskId: "results-layout-diagnostic",
            ParentTaskId: null,
            ProjectId: null,
            TaskType: "system.diagnostic_snapshot",
            Status: "Completed",
            Priority: 50,
            ResourceTag: "system-diagnostic",
            Payload: JsonSerializer.SerializeToElement(new { schema_version = "1.0" }),
            AttemptCount: 1,
            MaxAttempts: 2,
            TimeoutSeconds: 30,
            CreatedAt: timestamp.AddSeconds(-5),
            UpdatedAt: timestamp,
            ErrorCode: null,
            ErrorMessage: null,
            ResultId: "result-layout-diagnostic");
        var viewModel = ResultsPageViewModel.CreateForSmokeTest(new[] { task });
        viewModel.SelectedResult = viewModel.VisibleResults.Single();
        var page = new ResultsPage { DataContext = viewModel };

        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(page.IsMeasureValid, "Results Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Results Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Results Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Results Page 实际高度无效");
    }
}
