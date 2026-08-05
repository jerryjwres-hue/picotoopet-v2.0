using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>锁定 Windows 固定结果卡片只接受 Slice D 白名单值。</summary>
internal static class DiagnosticResultContractSmokeTests
{
    private static readonly DiagnosticCheckResult[] CoreHealthyChecks =
    {
        new("core_health", "pass", "CORE_HEALTHY"),
    };

    private static readonly DiagnosticCheckResult[] UnknownChecks =
    {
        new("arbitrary_probe", "pass", "CORE_HEALTHY"),
    };

    private static readonly DiagnosticCheckResult[] QueueHealthyChecks =
    {
        new("queue_backlog", "pass", "QUEUE_HEALTHY"),
    };

    private static readonly DiagnosticCheckResult[] NullChecks =
    {
        null!,
    };

    private static readonly string[] TokenLeakWarnings =
    {
        "TOKEN_LEAK",
    };

    public static void Run()
    {
        var valid = CreateResult(
            checks: CoreHealthyChecks,
            warnings: Array.Empty<string>());
        var viewModel = DiagnosticResultViewModel.FromResult(valid);
        SmokeAssert.True(viewModel.IsAvailable, "合法固定结果未生成结果卡片");

        AssertInvalid(
            valid with { Checks = UnknownChecks },
            "未知检查名未被拒绝");
        AssertInvalid(
            valid with { Warnings = TokenLeakWarnings },
            "未知警告值未被拒绝");
        AssertInvalid(
            valid with
            {
                Queue = new DiagnosticQueueResult(
                    new Dictionary<string, int>
                    {
                        ["InjectedStatus"] = 1,
                    },
                    null),
                Checks = QueueHealthyChecks,
            },
            "未知队列状态未被拒绝");
        AssertInvalid(
            valid with
            {
                Core = new DiagnosticCoreResult(
                    null!,
                    "online",
                    3),
            },
            "运行时 null core.version 未转换为合同错误");
        AssertInvalid(
            valid with { Checks = NullChecks },
            "运行时 null 检查项未转换为合同错误");
    }

    private static DiagnosticSnapshotResult CreateResult(
        IReadOnlyList<DiagnosticCheckResult> checks,
        IReadOnlyList<string> warnings) => new(
        SchemaVersion: "1.0",
        GeneratedAt: new DateTimeOffset(2026, 8, 3, 12, 0, 0, TimeSpan.Zero),
        Core: new DiagnosticCoreResult("2.3.0", "online", 3),
        Worker: null,
        Queue: null,
        Checks: checks,
        Warnings: warnings);

    private static void AssertInvalid(
        DiagnosticSnapshotResult result,
        string message)
    {
        try
        {
            _ = DiagnosticResultViewModel.FromResult(result);
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }
}
