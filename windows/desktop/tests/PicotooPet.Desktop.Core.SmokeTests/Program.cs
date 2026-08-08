using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>零第三方包的核心行为验收入口。</summary>
internal static class Program
{
    /// <summary>运行确定性断言；任一失败返回非零退出码。</summary>
    [STAThread]
    private static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Contains(
                    "--expect-task-center-legacy-binding-failure",
                    StringComparer.Ordinal))
            {
                TaskCenterWpfLayoutSmokeTests.RunExpectingLegacyBindingFailure();
                Console.WriteLine("PHASE23_TASK_CENTER_LEGACY_BINDING_RED=PASS");
                return 0;
            }

            VerifyLatencyPercentiles();
            VerifyReconnectBounds();
            VerifyStateDeduplication();
            CapabilitySmokeTests.Run();
            WorkerStatusSmokeTests.Run();
            StateStoreSmokeTests.Run();
            NavigationSmokeTests.Run();
            NavigationFaultBoundarySmokeTests.Run();
            NavigationContentRenderingSmokeTests.Run();
            ShellNavigationReconnectWpfSmokeTests.Run();
            TaskCenterSmokeTests.Run();
            ResultsCenterSmokeTests.Run();
            ApprovalCenterSmokeTests.Run();
            CloudDevelopmentSmokeTests.Run();
            DevBrokerPolicySmokeTests.Run();
            DevBrokerProcessSmokeTests.Run();
            DiagnosticTaskActionStateSmokeTests.Run();
            DiagnosticResultContractSmokeTests.Run();
            ProductVersionWpfSmokeTests.Run();
            TaskCenterWpfLayoutSmokeTests.Run();
            ResultsPageWpfLayoutSmokeTests.Run();
            ApprovalsPageWpfLayoutSmokeTests.Run();
            CloudDevelopmentPageWpfLayoutSmokeTests.Run();
            ProviderReviewPanelWpfLayoutSmokeTests.Run();
            PlatformFoundationPagesWpfLayoutSmokeTests.Run();
            await RetryableOperationSmokeTests.RunAsync().ConfigureAwait(false);
            await BoundedDiagnosticResultSmokeTests.RunAsync().ConfigureAwait(false);
            await BoundedApiErrorSmokeTests.RunAsync().ConfigureAwait(false);
            await DiagnosticSnapshotSmokeTests.RunAsync().ConfigureAwait(false);
            await HandoffPreparationSmokeTests.RunAsync().ConfigureAwait(false);
            await CloudDevelopmentPhase10ASmokeTests.RunAsync().ConfigureAwait(false);
            await CodexHandoffTemplateSmokeTests.RunAsync().ConfigureAwait(false);
            await MacCoreReturnClientSmokeTests.RunAsync().ConfigureAwait(false);
            await MacCoreBrokerClientSmokeTests.RunAsync().ConfigureAwait(false);
            await ProviderSessionSmokeTests.RunAsync().ConfigureAwait(false);
            await ProviderReviewSmokeTests.RunAsync().ConfigureAwait(false);
            await ReturnValidationSmokeTests.RunAsync().ConfigureAwait(false);
            await BrokerSessionSmokeTests.RunAsync().ConfigureAwait(false);
            await EventStreamColdStartSmokeTests.RunAsync().ConfigureAwait(false);
            await StateSyncCoordinatorSmokeTests.RunAsync().ConfigureAwait(false);
            Console.WriteLine("PHASE2_CORE_SMOKE=PASS");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"PHASE2_CORE_SMOKE=FAIL | {exception}");
            return 1;
        }
    }

    private static void VerifyLatencyPercentiles()
    {
        var recorder = new LatencyRecorder(128);
        foreach (var value in Enumerable.Range(1, 100))
        {
            recorder.Add(value);
        }
        var summary = recorder.Snapshot();
        Assert(summary.P50Milliseconds == 50, "p50 计算错误");
        Assert(summary.P95Milliseconds == 95, "p95 计算错误");
        Assert(summary.P99Milliseconds == 99, "p99 计算错误");
        Assert(summary.MaximumMilliseconds == 100, "最大值错误");
    }

    private static void VerifyReconnectBounds()
    {
        var policy = new ReconnectPolicy(
            TimeSpan.FromMilliseconds(200),
            TimeSpan.FromSeconds(5),
            jitterMilliseconds: 0);
        Assert(policy.GetDelay(0) == TimeSpan.FromMilliseconds(200), "首轮重连超时");
        Assert(policy.GetDelay(8) == TimeSpan.FromSeconds(5), "重连上限错误");
    }

    private static void VerifyStateDeduplication()
    {
        var store = new AppStateStore();
        var payload = JsonSerializer.SerializeToElement(new
        {
            task_id = "task-1",
            parent_task_id = (string?)null,
            project_id = (string?)null,
            task_type = "analysis",
            status = "Queued",
            priority = 100,
            resource_tag = (string?)null,
            payload = new { },
            attempt_count = 0,
            max_attempts = 3,
            timeout_seconds = 3600,
            created_at = DateTimeOffset.UtcNow,
            updated_at = DateTimeOffset.UtcNow,
            error_code = (string?)null,
            error_message = (string?)null,
            result_id = (string?)null,
        });
        var first = new EventEnvelope(
            "2.2.0",
            1,
            "event-1",
            "task.updated",
            null,
            DateTimeOffset.UtcNow,
            payload);
        Assert(store.Apply(first), "首个事件未应用");
        Assert(!store.Apply(first), "重复事件未去重");
        Assert(store.Snapshot.Tasks.Count == 1, "任务状态数量错误");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
