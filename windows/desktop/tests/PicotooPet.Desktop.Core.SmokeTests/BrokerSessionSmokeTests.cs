using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 approved 门、Broker 状态进度、取消和同一 Session 预览保持。</summary>
internal static class BrokerSessionSmokeTests
{
    public static async Task RunAsync()
    {
        var approved = CreateHandoff("approved");
        var completed = CreateSession(
            "completed",
            updatedSeconds: 0,
            returnId: "253704fb-3ce7-4368-ae0e-9520c21ec022");
        var gateway = new FixtureGateway(approved, completed);
        var page    = new BrokerSessionViewModel(gateway);

        await page.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.CanStart, "approved Handoff 未启用 Mock Dev Broker");
        SmokeAssert.True(page.IsPreviewVisible, "已有 Broker Session 未显示安全预览");
        SmokeAssert.Equal(
            "local-mock-dev-broker",
            page.SelectedSession?.Provider,
            "Broker Provider 不是固定值");
        SmokeAssert.True(
            page.SafetyNotice.Contains("30 秒", StringComparison.Ordinal),
            "Broker 预览没有固定硬超时说明");

        var preview = page.SelectedSession;
        gateway.NextSessions = [CreateSession(
            "completed",
            updatedSeconds: 5,
            returnId: "253704fb-3ce7-4368-ae0e-9520c21ec022")];
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "同一 session_id 刷新后预览被隐藏");
        SmokeAssert.True(
            ReferenceEquals(preview, page.SelectedSession),
            "同一 session_id 等价刷新后预览对象被替换");

        gateway.ThrowOnListSessions = true;
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "Broker 刷新失败后已有预览被清空");
        SmokeAssert.True(
            page.StatusMessage.Contains("保留", StringComparison.Ordinal),
            "Broker 刷新失败没有说明预览已保留");

        var unapprovedPage = new BrokerSessionViewModel(
            new FixtureGateway(CreateHandoff("prepared"), completed));
        await unapprovedPage.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(!unapprovedPage.CanStart, "未批准 Handoff 错误启用了 Broker");

        var running = CreateSession("running", updatedSeconds: 1, returnId: null);
        var cancelGateway = new FixtureGateway(approved, running)
        {
            NextSessions = [running],
        };
        var cancelPage = new BrokerSessionViewModel(cancelGateway);
        await cancelPage.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(cancelPage.CanCancel, "running Broker Session 未启用取消");
        await cancelPage.CancelAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(1, cancelGateway.CancelCount, "Broker 取消没有调用固定网关");
        SmokeAssert.Equal(
            "cancelled",
            cancelPage.SelectedSession?.Status,
            "Broker 取消后安全投影状态错误");
    }

    private static HandoffRecord CreateHandoff(string status) => new(
        "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "验证 Mock Dev Broker",
        "运行固定沙盒、进程边界和 Return 导回验证。",
        status,
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase10b-mock-dev-broker",
        "d3ad0c5d4d2d09b277078d0d03b6ddaeab402d13",
        "internal",
        1,
        1,
        ["python-regression", "windows-wpf-behavior", "mac-core-arm64"],
        "20 turns · 30 秒 Broker · 1 并发 · 无真实 Provider",
        new string('a', 64),
        new string('b', 64),
        "approval-broker-001",
        new DateTimeOffset(2026, 8, 6, 0, 0, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 1, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 30, 0, TimeSpan.Zero),
        ["External Provider execution is disabled."]);

    private static BrokerSessionRecord CreateSession(
        string status,
        int updatedSeconds,
        string? returnId) => new(
        "153704fb-3ce7-4368-ae0e-9520c21ec022",
        "e55edbbb-a71f-4bb3-9d4c-e453654e5579",
        status,
        "local-mock-dev-broker",
        30,
        new string('a', 64),
        new string('b', 64),
        returnId,
        status == "completed" ? 4 : 0,
        status == "completed" ? new string('c', 64) : null,
        null,
        new DateTimeOffset(2026, 8, 6, 0, 2, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 6, 0, 2, updatedSeconds, TimeSpan.Zero),
        status is "completed" or "cancelled"
            ? new DateTimeOffset(2026, 8, 6, 0, 2, updatedSeconds, TimeSpan.Zero)
            : null,
        "仅完成固定 Mock Provider 沙盒、进程边界和 Return 合同验证。");

    private sealed class FixtureGateway(
        HandoffRecord handoff,
        BrokerSessionRecord initialSession) : IBrokerSessionGateway
    {
        public BrokerSessionRecord[] NextSessions { get; set; } = [initialSession];
        public bool ThrowOnListSessions { get; set; }
        public int CancelCount { get; private set; }

        public Task<HandoffRecord[]> GetHandoffsAsync(
            CancellationToken cancellationToken) =>
            Task.FromResult(new[] { handoff });

        public Task<BrokerSessionRecord[]> GetBrokerSessionsAsync(
            CancellationToken cancellationToken)
        {
            if (ThrowOnListSessions)
            {
                throw new ApiException(
                    "NETWORK_ERROR",
                    "fixture broker network error",
                    retryable: true,
                    "fixture-broker-trace",
                    statusCode: 0);
            }
            return Task.FromResult(NextSessions);
        }

        public Task<BrokerSessionRecord> RunMockBrokerAsync(
            HandoffRecord selectedHandoff,
            string idempotencyKey,
            IProgress<BrokerSessionRecord> progress,
            CancellationToken cancellationToken)
        {
            progress.Report(initialSession);
            return Task.FromResult(initialSession);
        }

        public Task<BrokerSessionRecord> CancelBrokerAsync(
            string sessionId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            CancelCount++;
            return Task.FromResult(CreateSession(
                "cancelled",
                updatedSeconds: 9,
                returnId: null));
        }
    }
}
