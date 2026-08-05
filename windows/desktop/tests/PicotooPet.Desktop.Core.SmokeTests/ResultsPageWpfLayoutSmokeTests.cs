using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
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

        var preview = DiagnosticResultViewModel.FromError("已加载的固定诊断预览");
        SetPrivateProperty(viewModel, nameof(ResultsPageViewModel.DiagnosticPreview), preview);
        SetPrivateProperty(viewModel, nameof(ResultsPageViewModel.IsPreviewVisible), true);
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        var store = new AppStateStore();
        store.ReplaceTasks(new[] { task with { UpdatedAt = timestamp.AddSeconds(5) } });
        viewModel.UpdateSnapshot(new ControlCenterSessionSnapshot(
            "http://127.0.0.1:8765",
            store.ControlCenterSnapshot,
            "online · 2.3.8.1",
            "REST p95 1.0 ms",
            "双机控制链已连接。"));
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);
        page.UpdateLayout();

        SmokeAssert.True(viewModel.IsPreviewVisible, "WPF ItemsSource 刷新后安全预览被隐藏");
        SmokeAssert.True(
            ReferenceEquals(preview, viewModel.DiagnosticPreview),
            "WPF ItemsSource 刷新后安全预览对象被清空或替换");
        SmokeAssert.True(page.IsMeasureValid, "Results Page 刷新后 Measure 失效");
        SmokeAssert.True(page.IsArrangeValid, "Results Page 刷新后 Arrange 失效");
    }

    private static void SetPrivateProperty<T>(
        ResultsPageViewModel viewModel,
        string propertyName,
        T value)
    {
        var setter = typeof(ResultsPageViewModel)
            .GetProperty(propertyName, BindingFlags.Instance | BindingFlags.Public)?
            .GetSetMethod(nonPublic: true)
            ?? throw new InvalidOperationException($"缺少结果中心属性 setter：{propertyName}。");
        setter.Invoke(viewModel, new object?[] { value });
    }
}
