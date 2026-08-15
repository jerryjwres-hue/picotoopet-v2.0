using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结桌宠事实投影优先级；测试先于生产实现进入分支。</summary>
internal static class InteractivePetSmokeTests
{
    private static readonly string[] SupportedTaskTypes = new[]
    {
        "system.diagnostic_snapshot",
        "business.local_intelligence.v1",
        "creative.content_plan.v1",
    };

    /// <summary>在常规 smoke Main 之前执行；旧 Task Center 专项 RED 模式保持隔离。</summary>
    [ModuleInitializer]
    public static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Contains(
                "--expect-task-center-legacy-binding-failure",
                StringComparer.Ordinal))
        {
            return;
        }
        Run();
    }

    public static void Run()
    {
        var presentationType = typeof(ShellViewModel).Assembly.GetType(
            "PicotooPet.Desktop.ViewModels.AssistantPetPresentation");
        SmokeAssert.True(presentationType is not null, "桌宠事实投影 AssistantPetPresentation 尚未实现");

        var fromSnapshot = presentationType!.GetMethod(
            "FromSnapshot",
            BindingFlags.Public | BindingFlags.Static);
        SmokeAssert.True(fromSnapshot is not null, "桌宠事实投影必须公开 FromSnapshot");

        VerifyMode(
            fromSnapshot!,
            Snapshot(ConnectionState.Faulted, workerAvailable: true, workerReason: "idle"),
            "Error");
        VerifyMode(
            fromSnapshot!,
            Snapshot(ConnectionState.Offline, workerAvailable: true, workerReason: "idle"),
            "Offline");
        VerifyMode(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "executing",
                Task("running", "Running")),
            "Working");
        VerifyMode(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "idle",
                Task("review", "NeedsHuman")),
            "Waiting");
        VerifyMode(
            fromSnapshot!,
            Snapshot(ConnectionState.Online, workerAvailable: true, workerReason: "idle"),
            "Resting");
        VerifyMode(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "executing",
                Task("running", "Running"),
                Task("review", "NeedsHuman")),
            "Working");
    }

    private static void VerifyMode(
        MethodInfo fromSnapshot,
        ControlCenterSessionSnapshot snapshot,
        string expected)
    {
        var presentation = fromSnapshot.Invoke(null, new object[] { snapshot });
        SmokeAssert.True(presentation is not null, "桌宠事实投影不能返回 null");
        var mode = presentation!.GetType().GetProperty("Mode")?.GetValue(presentation)?.ToString();
        SmokeAssert.True(
            string.Equals(mode, expected, StringComparison.Ordinal),
            $"桌宠状态错误：期望 {expected}，实际 {mode ?? "<null>"}");
    }

    private static ControlCenterSessionSnapshot Snapshot(
        ConnectionState connectionState,
        bool workerAvailable,
        string workerReason,
        params TaskRecord[] tasks)
    {
        var capabilities = ControlCenterCapabilities.Legacy22;
        var state = new ControlCenterSnapshot(
            new ConnectionSnapshot(connectionState, null),
            new CapabilitySnapshot(
                "2.3.0",
                capabilities,
                new ContractVersions("1.0", "1.0", "1.0"),
                "manual_approval_only"),
            new WorkerSnapshot(
                "2.3.0",
                workerAvailable,
                workerAvailable ? "online" : "offline",
                workerReason,
                "worker-pet-smoke",
                SupportedTaskTypes,
                DateTimeOffset.UtcNow),
            new TaskStateSnapshot(tasks, 1, false, tasks.LastOrDefault()));
        return new ControlCenterSessionSnapshot(
            "http://127.0.0.1:8765",
            state,
            "pet-smoke",
            "REST p95 1 ms",
            "pet-smoke");
    }

    private static TaskRecord Task(string id, string status)
    {
        var now = DateTimeOffset.UtcNow;
        return new TaskRecord(
            id,
            null,
            null,
            "business.local_intelligence.v1",
            status,
            100,
            null,
            JsonSerializer.SerializeToElement(new { }),
            0,
            3,
            3600,
            now.AddMinutes(-1),
            now,
            null,
            null,
            null);
    }
}
