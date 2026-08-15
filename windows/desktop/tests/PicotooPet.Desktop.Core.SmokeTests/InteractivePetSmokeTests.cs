using System.Collections;
using System.Reflection;
using System.Resources;
using System.Runtime.CompilerServices;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结桌宠事实投影、状态灯、多帧交互和简单模式视觉接入合同。</summary>
internal static class InteractivePetSmokeTests
{
    private static readonly string[] SupportedTaskTypes = new[]
    {
        "system.diagnostic_snapshot",
        "business.local_intelligence.v1",
        "creative.content_plan.v1",
    };

    private static readonly string[] RequiredPetResources = new[]
    {
        "assets/pet/husky/v1/idle_0.png",
        "assets/pet/husky/v1/idle_1.png",
        "assets/pet/husky/v1/working_0.png",
        "assets/pet/husky/v1/working_1.png",
        "assets/pet/husky/v1/working_2.png",
        "assets/pet/husky/v1/resting_0.png",
        "assets/pet/husky/v1/resting_1.png",
        "assets/pet/husky/v1/resting_2.png",
        "assets/pet/husky/v1/offline_0.png",
        "assets/pet/husky/v1/offline_1.png",
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

        VerifyShellIsolationContract();
        VerifyNativePetControlContract(presentationType);
        VerifySimpleModeVisualContract();
        VerifyPetResources();
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

    private static void VerifyShellIsolationContract()
    {
        var shellType = typeof(PicotooPet.Desktop.Views.ShellWindow);
        var applyMethod = shellType.GetMethod(
            "ApplyAssistantPetSnapshot",
            BindingFlags.NonPublic | BindingFlags.Instance);
        SmokeAssert.True(applyMethod is not null, "现有 WPF Shell 必须提供隔离的桌宠快照适配器");
        SmokeAssert.True(
            applyMethod!.ReturnType == typeof(void)
            && applyMethod.GetParameters() is [{ ParameterType: var parameterType }]
            && parameterType == typeof(ControlCenterSessionSnapshot),
            "桌宠适配器必须只消费 ControlCenterSessionSnapshot 且不返回业务命令");

        var shellViewModelProperty = typeof(ShellViewModel).GetProperty(
            "PetPresentation",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(
            shellViewModelProperty is null,
            "桌宠不应把视觉状态写入 ShellViewModel，避免侵入现有导航与业务结构");
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

        var timerField = controlType.GetField(
            "_frameTimer",
            BindingFlags.NonPublic | BindingFlags.Instance);
        SmokeAssert.True(timerField is not null, "桌宠必须使用本地多帧定时器，而不是只移动一张静态图");
        SmokeAssert.True(
            timerField!.FieldType.FullName == "System.Windows.Threading.DispatcherTimer",
            "桌宠多帧驱动必须留在原生 WPF Dispatcher 内");

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

    private static void VerifySimpleModeVisualContract()
    {
        var shellType = typeof(PicotooPet.Desktop.Views.ShellWindow);
        var petField = shellType.GetField(
            "AssistantPet",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        SmokeAssert.True(petField is not null, "现有 Shell 左侧栏必须直接承载 AssistantPet，不得另起第二程序");

        var homeType = typeof(PicotooPet.Desktop.Views.Pages.OperatorHomePage);
        foreach (var fieldName in new[] { "HeroCard", "SystemStatusCard", "TaskOverviewCard", "RecentTasksCard" })
        {
            var field = homeType.GetField(
                fieldName,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            SmokeAssert.True(field is not null, $"简单模式首页缺少设计稿核心区域 {fieldName}");
        }
    }

    private static void VerifyPetResources()
    {
        var assembly = typeof(ShellViewModel).Assembly;
        var resourceName = assembly
            .GetManifestResourceNames()
            .SingleOrDefault(name => name.EndsWith(".g.resources", StringComparison.OrdinalIgnoreCase));
        SmokeAssert.True(resourceName is not null, "WPF 程序缺少编译资源容器");

        using var stream = assembly.GetManifestResourceStream(resourceName!);
        SmokeAssert.True(stream is not null, "无法读取 WPF 编译资源容器");
        using var reader = new ResourceReader(stream!);
        var keys = reader
            .Cast<DictionaryEntry>()
            .Select(entry => entry.Key?.ToString()?.ToLowerInvariant())
            .Where(key => !string.IsNullOrWhiteSpace(key))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        foreach (var resource in RequiredPetResources)
        {
            SmokeAssert.True(keys.Contains(resource), $"桌宠多帧资源缺失：{resource}");
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
