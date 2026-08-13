using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 页面上验证任务中心绑定和诊断结果刷新可以完成布局。</summary>
internal static class TaskCenterWpfLayoutSmokeTests
{
    /// <summary>在专用 STA 线程构造修复后的页面，并传播任意布局异常。</summary>
    public static void Run()
    {
        RunOnDedicatedStaThread(RunFixedLayout);
        RunOnDedicatedStaThread(RunVisibleDiagnosticRefreshLayout);
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

    /// <summary>让真实诊断结果卡参与 DataBind 和布局，再刷新同一逻辑任务。</summary>
    private static void RunVisibleDiagnosticRefreshLayout()
    {
        var timestamp = new DateTimeOffset(2026, 8, 13, 15, 11, 42, TimeSpan.Zero);
        var diagnostic = new TaskRecord(
            TaskId: "diagnostic-visible-refresh",
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
            CreatedAt: timestamp,
            UpdatedAt: timestamp,
            ErrorCode: null,
            ErrorMessage: null,
            ResultId: "diagnostic-result-visible");
        var viewModel = TaskCenterPageViewModel.CreateForSmokeTest(
            new[] { diagnostic },
            WorkerSnapshot.NotDeployed);
        SetDiagnosticCard(viewModel);
        var page = new TaskCenterPage
        {
            DataContext = viewModel,
        };

        Layout(page);
        var diagnosticBorder = FindDiagnosticBorder(page)
            ?? throw new InvalidOperationException("真实 WPF 页面没有生成诊断结果 Border。");
        SmokeAssert.Equal(
            Visibility.Visible,
            diagnosticBorder.Visibility,
            "刷新前诊断结果 Border 没有真正显示");

        InvokeApplySnapshot(
            viewModel,
            new[] { diagnostic with { UpdatedAt = timestamp.AddSeconds(1) } },
            WorkerSnapshot.NotDeployed);
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        Layout(page);

        SmokeAssert.True(
            viewModel.IsDiagnosticResultVisible && viewModel.DiagnosticResult is not null,
            "同 task_id snapshot 刷新后诊断结果状态丢失");
        diagnosticBorder = FindDiagnosticBorder(page)
            ?? throw new InvalidOperationException("snapshot 刷新后诊断结果 Border 消失。");
        SmokeAssert.Equal(
            Visibility.Visible,
            diagnosticBorder.Visibility,
            "同 task_id snapshot 刷新后诊断结果 Border 被折叠");
        SmokeAssert.True(page.IsMeasureValid, "诊断结果刷新后 Task Center Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "诊断结果刷新后 Task Center Arrange 未完成");
    }

    /// <summary>构造含只读优先级和超时字段的页面，并执行完整布局流水线。</summary>
    private static TaskCenterPage RunLayoutPipeline()
    {
        var timestamp = new DateTimeOffset(2026, 8, 2, 20, 0, 0, TimeSpan.Zero);
        var task = new TaskRecord(
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

        Layout(page);
        return page;
    }

    private static void Layout(TaskCenterPage page)
    {
        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
    }

    /// <summary>仅用反射准备测试状态，不为烟测扩大生产 ViewModel API。</summary>
    private static void SetDiagnosticCard(TaskCenterPageViewModel viewModel)
    {
        SetPrivateProperty(
            viewModel,
            nameof(TaskCenterPageViewModel.DiagnosticResult),
            DiagnosticResultViewModel.FromError("fixture diagnostic result"));
        SetPrivateProperty(
            viewModel,
            nameof(TaskCenterPageViewModel.IsDiagnosticResultVisible),
            true);
    }

    private static void SetPrivateProperty(
        TaskCenterPageViewModel viewModel,
        string propertyName,
        object value)
    {
        var property = typeof(TaskCenterPageViewModel).GetProperty(
            propertyName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"{propertyName} 属性不存在。");
        property.SetValue(viewModel, value);
    }

    /// <summary>通过私有快照入口模拟 Session 更新。</summary>
    private static void InvokeApplySnapshot(
        TaskCenterPageViewModel viewModel,
        IReadOnlyList<TaskRecord> tasks,
        WorkerSnapshot worker)
    {
        var method = typeof(TaskCenterPageViewModel).GetMethod(
            "ApplySnapshot",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("ApplySnapshot 方法不存在。");
        method.Invoke(viewModel, new object[] { tasks, worker });
    }

    private static Border? FindDiagnosticBorder(DependencyObject root)
    {
        if (root is Border border && border.DataContext is DiagnosticResultViewModel)
        {
            return border;
        }

        var count = VisualTreeHelper.GetChildrenCount(root);
        for (var index = 0; index < count; index++)
        {
            var match = FindDiagnosticBorder(VisualTreeHelper.GetChild(root, index));
            if (match is not null)
            {
                return match;
            }
        }
        return null;
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