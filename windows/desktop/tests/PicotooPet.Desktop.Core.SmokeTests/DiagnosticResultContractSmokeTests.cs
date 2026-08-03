using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>锁定 Windows 固定结果卡片只接受 Slice D 白名单值。</summary>
internal static class DiagnosticResultContractSmokeTests
{
    public static void Run()
    {
        var valid = CreateResult(
            checks: new[]
            {
                new DiagnosticCheckResult(
                    "core_health",
                    "pass",
                    "CORE_HEALTHY"),
            },
            warnings: Array.Empty<string>());
        var viewModel = DiagnosticResultViewModel.FromResult(valid);
        SmokeAssert.True(viewModel.IsAvailable, "合法固定结果未生成结果卡片");

        AssertInvalid(
            valid with
            {
                Checks = new[]
                {
                    new DiagnosticCheckResult(
                        "arbitrary_probe",
                        "pass",
                        "CORE_HEALTHY"),
                },
            },
            "未知检查名未被拒绝");
        AssertInvalid(
            valid with { Warnings = new[] { "TOKEN_LEAK" } },
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
                Checks = new[]
                {
                    new DiagnosticCheckResult(
                        "queue_backlog",
                        "pass",
                        "QUEUE_HEALTHY"),
                },
            },
            "未知队列状态未被拒绝");
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
