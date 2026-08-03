using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 页面上验证任务中心绑定可以完成布局。</summary>
internal static class TaskCenterWpfLayoutSmokeTests
{
    /// <summary>在专用 STA 线程构造修复后的页面，并传播任意布局异常。</summary>
    public static void Run()
    {
        RunOnDedicatedStaThread(RunFixedLayout);
    }

    /// <summary>要求历史默认绑定在真实页面布局中产生只读属性异常。</summary>
    public static void RunExpectingLegacyBindingFailure()
    {
        RunOnDedicatedStaThread(() =>
        {
            try
            {
                RunLayoutPipeline();
            }
            catch (Exception exception)
            {
                var bindingFailure = FindLegacyBindingFailure(exception);
                if (bindingFailure is not null)
                {
                    return;
                }

                throw new InvalidOperationException(
                    "历史绑定触发了异常，但不是预期的 WPF 只读属性 InvalidOperationException。",
                    exception);
            }

            throw new InvalidOperationException(
                "历史绑定没有触发预期的 WPF 只读属性 InvalidOperationException。");
        });
    }

    private static void RunOnDedicatedStaThread(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
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

    private static void RunFixedLayout()
    {
        var page = RunLayoutPipeline();
        SmokeAssert.True(page.IsMeasureValid, "Task Center Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Task Center Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Task Center 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Task Center 实际高度无效");
    }

    /// <summary>构造含只读优先级和超时字段的页面，并执行完整布局流水线。</summary>
    private static TaskCenterPage RunLayoutPipeline()
    {
        var timestamp = new DateTimeOffset(2026, 8, 2, 20, 0, 0, TimeSpan.Zero);
        var task      = new TaskRecord(
            TaskId: "task-center-layout-regression",
            ParentTaskId: null,
            ProjectId: "project-layout-regression",
            TaskType: "analysis",
            Status: "Queued",
            Priority: 100,
            ResourceTag: null,
            Payload: JsonSerializer.SerializeToElement(new { prompt = "layout fixture" }),
            AttemptCount: 0,
            MaxAttempts: 3,
            TimeoutSeconds: 3600,
            CreatedAt: timestamp,
            UpdatedAt: timestamp,
            ErrorCode: null,
            ErrorMessage: null);
        var viewModel = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { task },
            WorkerSnapshot.NotDeployed);
        var page = new TaskCenterPage
        {
            DataContext = viewModel,
        };

        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        return page;
    }

    private static InvalidOperationException? FindLegacyBindingFailure(Exception exception)
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            if (current is not InvalidOperationException invalidOperation)
            {
                continue;
            }

            var message = invalidOperation.Message;
            var namesReadOnlyProperty =
                message.Contains("Priority", StringComparison.Ordinal) ||
                message.Contains("TimeoutSeconds", StringComparison.Ordinal);
            var namesInvalidBindingMode =
                message.Contains("TwoWay", StringComparison.OrdinalIgnoreCase) ||
                message.Contains("OneWayToSource", StringComparison.OrdinalIgnoreCase) ||
                message.Contains("read-only", StringComparison.OrdinalIgnoreCase) ||
                message.Contains("只读", StringComparison.Ordinal);
            if (namesReadOnlyProperty && namesInvalidBindingMode)
            {
                return invalidOperation;
            }
        }

        return null;
    }
}
