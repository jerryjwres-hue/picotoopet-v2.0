using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Phase 10D-A Windows Provider 控制面的确定性行为合同。</summary>
internal static class ProviderSessionSmokeTests
{
    public static async Task RunAsync()
    {
        var gateway = new FakeProviderGateway();
        var viewModel = new ProviderSessionViewModel(gateway);

        await viewModel.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("ready", viewModel.ProviderStatus.Readiness, "Provider 就绪状态未加载");
        SmokeAssert.Equal(1, viewModel.EligibleHandoffs.Count, "只应展示 approved Codex Handoff");
        SmokeAssert.True(viewModel.CanConfirmUsage, "approved Codex Handoff 应允许人工额度确认");

        viewModel.SelectedUsageStatus = "confirmed_available";
        await viewModel.ConfirmUsageAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(viewModel.CanStartSession, "额度确认后应允许启动一次低预算 Session");
        SmokeAssert.Equal(8, viewModel.LatestConfirmation!.Budget.MaxTurns, "Windows 不得扩大 turn 预算");
        SmokeAssert.Equal(900, viewModel.LatestConfirmation.Budget.TimeoutSeconds, "Windows 不得扩大时间预算");

        await viewModel.StartSessionAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("waiting_provider_ready", viewModel.SelectedSession!.Status, "Session 初始状态错误");
        SmokeAssert.True(viewModel.CanCancelSession, "活动 Session 必须允许取消");

        await viewModel.CancelSelectedSessionAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("cancelled", viewModel.SelectedSession!.Status, "取消状态未回写");
        SmokeAssert.True(!viewModel.CanCancelSession, "终态 Session 不得重复取消");
    }

    private sealed class FakeProviderGateway : IProviderSessionGateway
    {
        private readonly HandoffRecord _eligible = new(
            "handoff-codex",
            "picotoopet-repo-maintenance-codex-v1",
            "PicotooPet Codex 仓库维护",
            "低预算 Codex 修复",
            "只修改批准范围并返回安全结果。",
            "approved",
            "codex",
            ProviderConfigured: true,
            "https://github.com/jerryjwres-hue/picotoopet-v2.0",
            "feature/phase10d-budgeted-codex-provider-2.3.13.2",
            new string('a', 40),
            "internal",
            6,
            6,
            ["pytest", "windows-wpf"],
            "8 turns / 900 seconds / 5 files / no retries",
            new string('b', 64),
            new string('c', 64),
            "approval-codex",
            DateTimeOffset.UtcNow.AddMinutes(-5),
            DateTimeOffset.UtcNow.AddMinutes(-1),
            DateTimeOffset.UtcNow.AddMinutes(25),
            ["no push", "no merge"]);

        private ProviderSessionRecord? _session;

        public Task<ProviderStatusRecord> GetStatusAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new ProviderStatusRecord(
                "codex",
                "ready",
                RealExecutionDefault: false,
                UsageMachineReadable: false,
                "mac-worker",
                "Mac Worker 已检测到本机 Codex CLI 和可用认证。"));

        public Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new[]
            {
                _eligible,
                _eligible with { HandoffId = "manual", Provider = "manual" },
                _eligible with { HandoffId = "pending", Status = "approval_pending" },
            });

        public Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken) =>
            Task.FromResult(_session is null ? Array.Empty<ProviderSessionRecord>() : new[] { _session });

        public Task<ProviderUsageConfirmationRecord> ConfirmUsageAsync(
            string handoffId,
            string usageStatus,
            string idempotencyKey,
            CancellationToken cancellationToken) =>
            Task.FromResult(new ProviderUsageConfirmationRecord(
                "11111111-1111-1111-1111-111111111111",
                handoffId,
                "codex",
                usageStatus,
                _eligible.RequestDigest,
                _eligible.PackageDigest,
                ProviderBudgetRecord.Fixed,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow.AddMinutes(15)));

        public Task<ProviderSessionRecord> StartSessionAsync(
            string handoffId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            _session = new ProviderSessionRecord(
                "22222222-2222-2222-2222-222222222222",
                handoffId,
                "codex",
                "waiting_provider_ready",
                _eligible.RequestDigest,
                _eligible.PackageDigest,
                ProviderBudgetRecord.Fixed,
                0,
                0,
                0,
                null,
                null,
                ProviderUsageUnknown: true,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow,
                null,
                "固定低预算 Session。");
            return Task.FromResult(_session);
        }

        public Task<ProviderSessionRecord> CancelSessionAsync(
            string sessionId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            _session = _session! with
            {
                Status = "cancelled",
                FailureCode = "PROVIDER_CANCELLED",
                UpdatedAt = DateTimeOffset.UtcNow,
                FinishedAt = DateTimeOffset.UtcNow,
            };
            return Task.FromResult(_session);
        }
    }
}
