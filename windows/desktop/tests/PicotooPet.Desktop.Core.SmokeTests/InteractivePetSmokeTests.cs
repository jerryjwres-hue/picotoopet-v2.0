using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结桌宠事实投影、状态灯和原生 WPF 交互组件合同。</summary>
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

        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(ConnectionState.Faulted, workerAvailable: true, workerReason: "idle"),
            "Error",
            "Orange");
        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(ConnectionState.Offline, workerAvailable: true, workerReason: "idle"),
            "Offline",
            "Gray");
        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "executing",
                Task("running", "Running")),
            "Working",
            "Green");
        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "idle",
                Task("review", "NeedsHuman")),
            "Waiting",
            "Orange");
        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(ConnectionState.Online, workerAvailable: true, workerReason: "idle"),
            "Resting",
            "Green");
        VerifyModeAndIndicator(
            fromSnapshot!,
            Snapshot(
                ConnectionState.Online,
                workerAvailable: true,
                workerReason: "executing",
                Task("running", "Running"),
                Task("review", "NeedsHuman")),
            "Working",
            "Green");

        VerifyNativePetControlContract(presentationType);
    }

    private static void VerifyModeAndIndicator(
        MethodInfo fromSnapshot,
        ControlCenterSessionSnapshot snapshot,
        string expectedMode,
        string expectedIndicator)
    {
        var presentation = fromSnapshot.Invoke(null, new object[] { snapshot });
        SmokeAssert.True(presentation is not null, "桌宠事实投影不能返回 null");
        var mode = presentation!.GetType().GetProperty("Mode")?.GetValue(presentation)?.ToString();
        var indicator = presentation.GetType().GetProperty("Indicator")?.GetValue(presentation)?.ToString();
        SmokeAssert.True(
            string.Equals(mode, expectedMode, StringComparison.Ordinal),
            $"桌宠状态错误：期望 {expectedMode}，实际 {mode ?? "<null>"}");
        SmokeAssert.True(
            string.Equals(indicator, expectedIndicator, StringComparison.Ordinal),
            $"桌宠状态灯错误：期望 {expectedIndicator}，实际 {indicator ?? "<null>"}");
    }

    private static void VerifyNativePetControlContract(Type presentationType)
    {
        var controlType = typeof(ShellViewModel).Assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.AssistantPetPanel");
        SmokeAssert.True(controlType is not null, "必须在现有 WPF 程序内提供 AssistantPetPanel 原生控件");

        var presentationProperty = controlType!.GetProperty(
            "Presentation",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(presentationProperty is not null, "AssistantPetPanel 必须公开 Presentation 依赖属性");
        SmokeAssert.True(
            presentationProperty!.PropertyType == presentationType,
            "AssistantPetPanel 只能消费 AssistantPetPresentation，不得直接依赖 Session/Worker 服务");

        var forbidden = new[] { "Approve", "Reject", "CreateTask", "CancelTask", "Save", "Connect" };
        var publicDeclaredMethods = controlType
            .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Select(method => method.Name)
            .ToArray();
        foreach (var name in forbidden)
        {
            SmokeAssert.True(
                !publicDeclaredMethods.Any(method => method.Contains(name, StringComparison.OrdinalIgnoreCase)),
                $"桌宠 UI 不得暴露业务写入方法 {name}");
        }
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
