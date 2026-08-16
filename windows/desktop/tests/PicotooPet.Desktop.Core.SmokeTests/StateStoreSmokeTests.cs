using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证拆分后的连接、能力和任务状态仓库。</summary>
internal static class StateStoreSmokeTests
{
    /// <summary>执行 focused store 的确定性状态转换断言。</summary>
    public static void Run()
    {
        VerifyConnectionStore();
        VerifyCapabilityStore();
        VerifyTaskSequenceGap();
        VerifyHiddenSurvivesExecutionEvent();
    }

    private static void VerifyConnectionStore()
    {
        var connection = new ConnectionStateStore();
        connection.Set(ConnectionState.Reconnecting, "wifi_changed");

        SmokeAssert.True(
            connection.Snapshot.State == ConnectionState.Reconnecting,
            "连接状态未提交");
        SmokeAssert.True(
            connection.Snapshot.LastError == "wifi_changed",
            "连接错误摘要未保留");
    }

    private static void VerifyCapabilityStore()
    {
        var capability = new CapabilityStateStore();

        SmokeAssert.True(
            capability.Snapshot.Features.DurableQueue,
            "Legacy 2.2 耐久队列能力必须保留");
        SmokeAssert.True(
            !capability.Snapshot.Features.Dashboard,
            "未知 Dashboard 能力必须默认关闭");
        SmokeAssert.True(
            !capability.Snapshot.Features.ConnectorContractV1,
            "旧服务不得伪造 Connector 合同能力");
    }

    private static void VerifyTaskSequenceGap()
    {
        var taskStore = new TaskStateStore();

        SmokeAssert.True(
            taskStore.Apply(CreateEvent(sequence: 1)) == SequenceApplyResult.Applied,
            "首个事件未应用");
        SmokeAssert.True(
            taskStore.Apply(CreateEvent(sequence: 1)) == SequenceApplyResult.Duplicate,
            "重复事件未被识别");
        SmokeAssert.True(
            taskStore.Apply(CreateEvent(sequence: 3)) == SequenceApplyResult.GapDetected,
            "事件序号跳跃未被识别");
        SmokeAssert.True(
            taskStore.Snapshot.LastSequence == 1,
            "跳跃事件不得静默推进序号");
        SmokeAssert.True(
            taskStore.Snapshot.Tasks.Count == 1,
            "跳跃事件不得污染任务快照");
    }

    private static void VerifyHiddenSurvivesExecutionEvent()
    {
        var timestamp = DateTimeOffset.UtcNow;
        var store = new TaskStateStore();
        store.ReplaceTasks(new[]
        {
            new TaskRecord(
                "task-1",
                null,
                null,
                "analysis",
                "Cancelled",
                100,
                null,
                JsonSerializer.SerializeToElement(new { }),
                0,
                3,
                3600,
                timestamp,
                timestamp,
                null,
                null,
                null,
                true),
        });

        SmokeAssert.True(
            store.Apply(CreateEvent(sequence: 1)) == SequenceApplyResult.Applied,
            "隐藏任务的连续执行事件未应用");
        SmokeAssert.True(
            store.Snapshot.Tasks.Single().IsHidden,
            "队列执行事件不得冲掉 REST 已确认的已删除状态");
    }

    private static EventEnvelope CreateEvent(long sequence)
    {
        var timestamp = new DateTimeOffset(
            year: 2026,
            month: 8,
            day: 1,
            hour: 0,
            minute: 0,
            second: 0,
            offset: TimeSpan.Zero);
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
            created_at = timestamp,
            updated_at = timestamp,
            error_code = (string?)null,
            error_message = (string?)null,
        });

        return new EventEnvelope(
            "2.3.0",
            sequence,
            $"event-{sequence}",
            "task.updated",
            "trace-1",
            timestamp,
            payload);
    }
}
