using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Handoff 准备、预览保持、审批提交和错误边界。</summary>
internal static class CloudDevelopmentPhase10ASmokeTests
{
    public static async Task RunAsync()
    {
        var template = CreateTemplate();
        var prepared = CreateRecord("prepared", approvalId: null, updatedSeconds: 0);
        var gateway  = new FixtureGateway(template, prepared);
        var page     = new CloudDevelopmentPageViewModel(gateway);

        SmokeAssert.True(!page.ProviderConfigured, "Phase 10A 不得伪造 Provider 已配置");
        SmokeAssert.True(!page.CanPrepare, "空输入不得允许准备 Handoff");

        page.DraftTitle     = "准备安全修复";
        page.DraftObjective = "只生成受控摘要并提交审批。";
        SmokeAssert.True(
            !page.CanPrepare,
            "Mac Core 固定模板尚未加载时不得允许准备 Handoff");

        await page.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(1, page.TemplateOptions.Count, "模板加载数量错误");
        SmokeAssert.Equal(1, page.RecentHandoffs.Count, "最近 Handoff 加载数量错误");
        SmokeAssert.True(page.CanPrepare, "固定模板和合法输入就绪后未启用准备动作");

        await page.PrepareAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "准备完成后没有显示安全预览");
        SmokeAssert.Equal("prepared", page.SelectedHandoff?.Status, "准备状态错误");
        SmokeAssert.True(page.CanSubmitApproval, "prepared Handoff 未启用提交审批");
        var preview = page.SelectedHandoff;

        gateway.NextList = [CreateRecord("prepared", approvalId: null, updatedSeconds: 5)];
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "同一 handoff_id 刷新后预览被隐藏");
        SmokeAssert.True(
            ReferenceEquals(preview, page.SelectedHandoff),
            "同一 handoff_id 刷新后预览对象被替换");

        gateway.ThrowOnList = true;
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "刷新失败后已有预览被清空");
        SmokeAssert.True(
            page.StatusMessage.Contains("保留", StringComparison.Ordinal),
            "刷新失败没有说明已保留预览");
        gateway.ThrowOnList = false;

        await page.SubmitSelectedApprovalAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(
            "waiting_approval",
            page.SelectedHandoff?.Status,
            "提交审批后状态错误");
        SmokeAssert.True(!page.CanSubmitApproval, "重复提交审批仍被允许");
        SmokeAssert.Equal(1, gateway.SubmitCount, "审批提交次数错误");
    }

    private static HandoffTemplateRecord CreateTemplate() => new(
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase23-slice-d-diagnostic-snapshot-release",
        "5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb");

    private static HandoffRecord CreateRecord(
        string status,
        string? approvalId,
        int updatedSeconds) => new(
        "handoff-001",
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "准备安全修复",
        "只生成受控摘要并提交审批。",
        status,
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase23-slice-d-diagnostic-snapshot-release",
        "5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb",
        "internal",
        1,
        1,
        ["python-regression", "windows-wpf-behavior", "windows-formal-release", "mac-core-arm64"],
        "20 turns · 1800 秒 · 1 并发 · 无网络工具",
        new string('a', 64),
        new string('b', 64),
        approvalId,
        new DateTimeOffset(2026, 8, 5, 19, 30, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 19, 30, updatedSeconds, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 20, 0, 0, TimeSpan.Zero),
        ["Provider execution is disabled in Phase 10A."]);

    private sealed class FixtureGateway(
        HandoffTemplateRecord template,
        HandoffRecord prepared) : IHandoffGateway
    {
        public HandoffRecord[] NextList { get; set; } = [prepared];
        public bool ThrowOnList { get; set; }
        public int SubmitCount { get; private set; }

        public Task<HandoffTemplateRecord[]> GetTemplatesAsync(
            CancellationToken cancellationToken) =>
            Task.FromResult(new[] { template });

        public Task<HandoffRecord[]> GetHandoffsAsync(
            CancellationToken cancellationToken)
        {
            if (ThrowOnList)
            {
                throw new ApiException(
                    "NETWORK_ERROR",
                    "fixture network error",
                    retryable: true,
                    "fixture-trace",
                    statusCode: 0);
            }
            return Task.FromResult(NextList);
        }

        public Task<HandoffRecord> PrepareAsync(
            HandoffPrepareRequest request,
            string idempotencyKey,
            CancellationToken cancellationToken) =>
            Task.FromResult(prepared);

        public Task<HandoffRecord> SubmitApprovalAsync(
            string handoffId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            SubmitCount++;
            return Task.FromResult(CreateRecord(
                "waiting_approval",
                "approval-001",
                updatedSeconds: 10));
        }
    }
}
