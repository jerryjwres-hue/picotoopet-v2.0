using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Navigation;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证审批中心能力、筛选、过期边界和安全字段。</summary>
internal static class ApprovalCenterSmokeTests
{
    public static void Run()
    {
        var now = DateTimeOffset.UtcNow;
        var pending = Record(
            "approval-pending",
            "Pending",
            now.AddMinutes(-2),
            now.AddMinutes(8));
        var approved = Record(
            "approval-approved",
            "Approved",
            now.AddMinutes(-5),
            now.AddMinutes(5),
            "已核对范围");
        var expired = Record(
            "approval-expired",
            "Expired",
            now.AddMinutes(-20),
            now.AddMinutes(-10));

        var viewModel = ApprovalsPageViewModel.CreateForSmokeTest(
            new[] { approved, expired, pending });
        SmokeAssert.True(viewModel.AllApprovals.Count == 3, "审批列表数量错误");
        SmokeAssert.True(
            viewModel.AllApprovals[0].ApprovalId == pending.ApprovalId,
            "审批列表未按申请时间倒序");

        viewModel.SelectedFilter = ApprovalCenterFilter.Pending;
        SmokeAssert.True(
            viewModel.VisibleApprovals.Count == 1
            && viewModel.VisibleApprovals[0].ApprovalId == pending.ApprovalId,
            "待处理筛选错误");
        viewModel.SelectedApproval = viewModel.VisibleApprovals[0];
        viewModel.DecisionReason = "批准固定摘要";
        SmokeAssert.True(viewModel.CanApprove, "待处理审批填写原因后应可批准");
        SmokeAssert.True(viewModel.CanReject, "待处理审批填写原因后应可拒绝");

        viewModel.SelectedFilter = ApprovalCenterFilter.Expired;
        viewModel.SelectedApproval = viewModel.VisibleApprovals.Single();
        viewModel.DecisionReason = "不得处理过期项";
        SmokeAssert.True(!viewModel.CanApprove, "过期审批不得批准");
        SmokeAssert.True(!viewModel.CanReject, "过期审批不得拒绝");

        var publicNames = typeof(ApprovalRecord)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        SmokeAssert.True(
            !publicNames.Any(name => name.Contains("Token", StringComparison.OrdinalIgnoreCase)),
            "审批 DTO 不得暴露 Token 字段");
        SmokeAssert.True(
            !publicNames.Contains("Scope", StringComparer.Ordinal),
            "Windows 审批 DTO 不得暴露任意原始 Scope 正文");

        var shell = ShellViewModel.CreateForSmokeTest(
            ControlCenterCapabilities.Legacy22 with
            {
                ApprovalList = true,
                ApprovalDigest = true,
            });
        shell.Navigate(NavigationRoute.Approvals);
        SmokeAssert.True(
            shell.CurrentPage is ApprovalsPageViewModel,
            "审批能力完整时必须渲染原生审批页面");
    }

    private static ApprovalRecord Record(
        string approvalId,
        string status,
        DateTimeOffset requestedAt,
        DateTimeOffset expiresAt,
        string? reason = null) => new(
        ApprovalId: approvalId,
        TaskId: "task-" + approvalId,
        ApprovalType: "cloud_upload",
        ScopeSummary: "budget=0；target=approved-handoff.zip",
        RequestDigest: new string('a', 64),
        Status: status,
        RequestedBy: "mac-agent",
        ResolvedBy: status == "Pending" ? null : "owner",
        ExpiresAt: expiresAt,
        RequestedAt: requestedAt,
        ResolvedAt: status == "Pending" ? null : requestedAt.AddMinutes(1),
        DecisionReason: reason);
}
