using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Windows Provider 控制面：双 Provider 人工额度确认、Core 创建 Session 的观察与紧急取消。</summary>
internal static class ProviderSessionSmokeTests
{
    public static async Task RunAsync()
    {
        var gateway = new FakeProviderGateway();
        var viewModel = new ProviderSessionViewModel(gateway);

        await viewModel.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("ready", viewModel.ProviderStatus.Readiness, "Codex 就绪状态未加载");
        SmokeAssert.Equal("ready", viewModel.ClaudeCodeStatus.Readiness, "Claude Code 就绪状态未加载");
        SmokeAssert.Equal(2, viewModel.EligibleHandoffs.Count, "应展示 Core 已绑定的两类 approved Coding Handoff");

        viewModel.SelectedHandoff = viewModel.EligibleHandoffs.Single(item =>
            string.Equals(item.Provider, "claude_code", StringComparison.Ordinal));
        viewModel.SelectedUsageStatus = "confirmed_available";
        SmokeAssert.True(viewModel.CanConfirmUsage, "approved Claude Code Handoff 应允许人工额度确认");

        await viewModel.ConfirmUsageAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("claude_code", viewModel.LatestConfirmation!.Provider, "额度确认必须绑定 Core 已选 Claude Code");
        SmokeAssert.Equal(8, viewModel.LatestConfirmation.Budget.MaxTurns, "Windows 不得扩大 turn 预算");
        SmokeAssert.Equal(900, viewModel.LatestConfirmation.Budget.TimeoutSeconds, "Windows 不得扩大时间预算");
        SmokeAssert.True(
            viewModel.StatusMessage.Contains("Mac Core", StringComparison.Ordinal),
            "额度确认后必须明确由 Mac Core 继续推进，不得提示 Windows 启动 Session");

        gateway.SeedCoreCreatedActiveSession("claude_code");
        await viewModel.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("claude_code", viewModel.SelectedSession!.Provider, "Windows 应观察 Core 创建的 Claude Session");
        SmokeAssert.Equal(
            "waiting_provider_ready",
            viewModel.SelectedSession.Status,
            "Windows 应能观察 Mac Core 创建的活动 Session");
        SmokeAssert.True(viewModel.CanCancelSession, "活动 Claude Session 必须允许紧急取消");

        await viewModel.CancelSelectedSessionAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("cancelled", viewModel.SelectedSession!.Status, "取消状态未回写");
        SmokeAssert.True(!viewModel.CanCancelSession, "终态 Session 不得重复取消");
    }

    private sealed class FakeProviderGateway : IProviderSessionGateway
    {
        private readonly HandoffRecord _codex = CreateHandoff(
            "handoff-codex",
            "picotoopet-repo-maintenance-codex-v1",
            "codex",
            "Codex",
            'b',
            'c');
        private readonly HandoffRecord _claudeCode = CreateHandoff(
            "handoff-claude-code",
            "picotoopet-repo-maintenance-claude-code-v1",
            "claude_code",
            "Claude Code",
            'd',
            'e');

        private ProviderSessionRecord? _session;

        public Task<ProviderStatusRecord> GetStatusAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new ProviderStatusRecord(
                "codex",
                "ready",
                RealExecutionDefault: false,
                UsageMachineReadable: false,
                "mac-worker",
                "Mac Worker 已检测到本机 Codex CLI 和可用认证。"));

        public Task<ProviderStatusRecord> GetClaudeCodeStatusAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new ProviderStatusRecord(
                "claude_code",
                "ready",
                RealExecutionDefault: false,
                UsageMachineReadable: false,
                "mac-worker",
                "Mac Worker 已检测到本机 Claude Code CLI 和可用认证。"));

        public Task<HandoffRecord[]> GetHandoffsAsync(CancellationToken cancellationToken) =>
            Task.FromResult(new[]
            {
                _codex,
                _claudeCode,
                _codex with { HandoffId = "manual", Provider = "manual" },
                _codex with { HandoffId = "pending", Status = "approval_pending" },
            });

        public Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken) =>
            Task.FromResult(_session is null ? Array.Empty<ProviderSessionRecord>() : new[] { _session });

        public Task<ProviderUsageConfirmationRecord> ConfirmUsageAsync(
            string handoffId,
            string usageStatus,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            var handoff = string.Equals(handoffId, _claudeCode.HandoffId, StringComparison.Ordinal)
                ? _claudeCode
                : _codex;
            return Task.FromResult(new ProviderUsageConfirmationRecord(
                "11111111-1111-1111-1111-111111111111",
                handoffId,
                handoff.Provider,
                usageStatus,
                handoff.RequestDigest,
                handoff.PackageDigest,
                ProviderBudgetRecord.Fixed,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow.AddMinutes(15)));
        }

        public void SeedCoreCreatedActiveSession(string provider)
        {
            var handoff = string.Equals(provider, "claude_code", StringComparison.Ordinal)
                ? _claudeCode
                : _codex;
            _session = new ProviderSessionRecord(
                "22222222-2222-2222-2222-222222222222",
                handoff.HandoffId,
                handoff.Provider,
                "waiting_provider_ready",
                handoff.RequestDigest,
                handoff.PackageDigest,
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
                "Mac Core Frugal 仲裁器创建的固定低预算 Session。");
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

        private static HandoffRecord CreateHandoff(
            string handoffId,
            string templateId,
            string provider,
            string displayName,
            char requestDigestChar,
            char packageDigestChar) => new(
            handoffId,
            templateId,
            $"PicotooPet {displayName} 仓库维护",
            $"低预算 {displayName} 修复",
            "只修改批准范围并返回安全结果。",
            "approved",
            provider,
            ProviderConfigured: true,
            "https://github.com/jerryjwres-hue/picotoopet-v2.0",
            "feature/frugal-coding-dual-provider",
            new string('a', 40),
            "internal",
            6,
            6,
            ["pytest", "windows-wpf"],
            "8 turns / 900 seconds / 5 files / no retries",
            new string(requestDigestChar, 64),
            new string(packageDigestChar, 64),
            $"approval-{provider}",
            DateTimeOffset.UtcNow.AddMinutes(-5),
            DateTimeOffset.UtcNow.AddMinutes(-1),
            DateTimeOffset.UtcNow.AddMinutes(25),
            ["no push", "no merge"]);
    }
}