using System.Runtime.ExceptionServices;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>在真实 STA WPF 页面验证审批列表、详情和决策绑定完成布局。</summary>
internal static class ApprovalsPageWpfLayoutSmokeTests
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
        var now = DateTimeOffset.UtcNow;
        var record = new ApprovalRecord(
            ApprovalId: "approval-layout",
            TaskId: "task-layout",
            ApprovalType: "cloud_upload",
            ScopeSummary: "budget=0；target=approved-handoff.zip",
            RequestDigest: new string('b', 64),
            Status: "Pending",
            RequestedBy: "mac-agent",
            ResolvedBy: null,
            ExpiresAt: now.AddMinutes(10),
            RequestedAt: now,
            ResolvedAt: null,
            DecisionReason: null);
        var viewModel = ApprovalsPageViewModel.CreateForSmokeTest(new[] { record });
        viewModel.SelectedApproval = viewModel.VisibleApprovals.Single();
        viewModel.DecisionReason = "批准固定摘要";
        var page = new ApprovalsPage { DataContext = viewModel };

        page.Measure(new Size(960, 680));
        page.Arrange(new Rect(0, 0, 960, 680));
        page.UpdateLayout();
        page.Dispatcher.Invoke(static () => { }, DispatcherPriority.DataBind);

        SmokeAssert.True(page.IsMeasureValid, "Approvals Page Measure 未完成");
        SmokeAssert.True(page.IsArrangeValid, "Approvals Page Arrange 未完成");
        SmokeAssert.True(page.ActualWidth > 0, "Approvals Page 实际宽度无效");
        SmokeAssert.True(page.ActualHeight > 0, "Approvals Page 实际高度无效");
        SmokeAssert.True(viewModel.CanApprove, "审批页面布局后动作状态错误");
    }
}
