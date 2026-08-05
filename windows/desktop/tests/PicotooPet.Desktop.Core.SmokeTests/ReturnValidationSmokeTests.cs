using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 approved 门、幂等重试、Return 预览保持和有界错误。</summary>
internal static class ReturnValidationSmokeTests
{
    public static async Task RunAsync()
    {
        var approved  = CreateHandoff("approved");
        var validated = CreateReturn("contract_validated", updatedSeconds: 0);
        var gateway = new FixtureGateway(approved, validated)
        {
            ThrowOnceOnRun = true,
        };
        var page = new ReturnValidationViewModel(gateway);

        await page.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.CanRunReturnSelfTest, "approved Handoff 未启用本地 Return 验证");

        await page.RunReturnSelfTestAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(2, gateway.RunCount, "瞬态错误后必须只重试一次");
        SmokeAssert.Equal(
            gateway.RunIdempotencyKeys[0],
            gateway.RunIdempotencyKeys[1],
            "Return 重试没有复用同一幂等键");
        SmokeAssert.True(page.IsPreviewVisible, "Return 验证后未显示安全预览");
        SmokeAssert.Equal(
            "contract_validated",
            page.SelectedReturn?.Status,
            "Return 合同验证状态错误");
        SmokeAssert.True(
            page.SelectedReturn?.ExecutionNotice.Contains("未运行", StringComparison.Ordinal) == true,
            "Return 预览没有明确声明未运行 Provider、代码或测试");

        var preview = page.SelectedReturn;
        gateway.NextReturns = [CreateReturn("contract_validated", updatedSeconds: 5)];
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "同一 return_id 刷新后预览被隐藏");
        SmokeAssert.True(
            ReferenceEquals(preview, page.SelectedReturn),
            "同一 return_id 刷新后预览对象被替换");

        gateway.ThrowOnListReturns = true;
        await page.RefreshAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(page.IsPreviewVisible, "Return 刷新失败后已有预览被清空");
        SmokeAssert.True(
            page.StatusMessage.Contains("保留", StringComparison.Ordinal),
            "Return 刷新失败没有说明预览已保留");

        var unapprovedGateway = new FixtureGateway(CreateHandoff("prepared"), validated);
        var unapprovedPage    = new ReturnValidationViewModel(unapprovedGateway);
        await unapprovedPage.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(
            !unapprovedPage.CanRunReturnSelfTest,
            "未批准 Handoff 错误启用了 Return 验证");
    }

    private static HandoffRecord CreateHandoff(string status) => new(
        "handoff-approved-001",
        "picotoopet-repo-maintenance-v1",
        "PicotooPet 仓库维护",
        "验证 Return 合同",
        "运行本地零变更 Return 合同验证。",
        status,
        "manual",
        ProviderConfigured: false,
        "https://github.com/jerryjwres-hue/picotoopet-v2.0",
        "feature/phase10a-handoff-preparation",
        "7a97694dfe4c1850def24d48b57ce8a8dbdee454",
        "internal",
        1,
        0,
        ["python-regression", "windows-wpf-behavior", "mac-core-arm64"],
        "20 turns · 1800 秒 · 1 并发 · 无网络工具",
        new string('a', 64),
        new string('b', 64),
        "approval-001",
        new DateTimeOffset(2026, 8, 5, 22, 0, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 1, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 30, 0, TimeSpan.Zero),
        ["Provider execution is disabled."]);

    private static ReturnRecord CreateReturn(string status, int updatedSeconds) => new(
        "return-001",
        "handoff-approved-001",
        status,
        "local-contract-self-test",
        new string('a', 64),
        new string('b', 64),
        new string('c', 64),
        ChangedFileCount: 0,
        EventCount: 3,
        [new ReturnValidationCheckRecord("return_contract", Passed: true)],
        [
            new ReturnEventSummaryRecord(1, "provider.session.started", "本地合同演练已开始。"),
            new ReturnEventSummaryRecord(2, "provider.progress", "正在验证固定 Return 合同。"),
            new ReturnEventSummaryRecord(3, "provider.returned", "零变更演练包已返回验证器。"),
        ],
        QuarantineCode: null,
        new DateTimeOffset(2026, 8, 5, 22, 2, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 8, 5, 22, 2, updatedSeconds, TimeSpan.Zero),
        "仅完成合同验证；未运行 Provider、代码、测试、构建、diff、worktree 或 Git 写操作。");

    private sealed class FixtureGateway(
        HandoffRecord handoff,
        ReturnRecord validated) : IReturnGateway
    {
        public ReturnRecord[] NextReturns { get; set; } = [validated];
        public bool ThrowOnceOnRun { get; set; }
        public bool ThrowOnListReturns { get; set; }
        public int RunCount { get; private set; }
        public List<string> RunIdempotencyKeys { get; } = [];

        public Task<HandoffRecord[]> GetHandoffsAsync(
            CancellationToken cancellationToken) =>
            Task.FromResult(new[] { handoff });

        public Task<ReturnRecord[]> GetReturnsAsync(
            CancellationToken cancellationToken)
        {
            if (ThrowOnListReturns)
            {
                throw new ApiException(
                    "NETWORK_ERROR",
                    "fixture return network error",
                    retryable: true,
                    "fixture-return-trace",
                    statusCode: 0);
            }
            return Task.FromResult(NextReturns);
        }

        public Task<ReturnRecord> RunReturnSelfTestAsync(
            string handoffId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            RunCount++;
            RunIdempotencyKeys.Add(idempotencyKey);
            if (ThrowOnceOnRun && RunCount == 1)
            {
                throw new ApiException(
                    "NETWORK_ERROR",
                    "fixture retryable return error",
                    retryable: true,
                    "fixture-return-run-trace",
                    statusCode: 0);
            }
            return Task.FromResult(validated);
        }
    }
}
