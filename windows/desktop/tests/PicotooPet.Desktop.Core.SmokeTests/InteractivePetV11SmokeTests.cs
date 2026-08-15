using System.Reflection;
using System.Runtime.CompilerServices;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v1.1 的悬浮桌宠、真实资源监控和动画生命周期合同。</summary>
internal static class InteractivePetV11SmokeTests
{
    /// <summary>在常规 WPF smoke 前验证新增表面存在且仍保持只读边界。</summary>
    [ModuleInitializer]
    public static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Contains(
                "--expect-task-center-legacy-binding-failure",
                StringComparer.Ordinal))
        {
            return;
        }

        VerifyFloatingPetContract();
        VerifyResourceMonitorContract();
        VerifyHomeResourceProjectionContract();
        VerifyAnimationLifecycleContract();
    }

    private static void VerifyFloatingPetContract()
    {
        var desktopAssembly = typeof(ShellViewModel).Assembly;
        var floatingType = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.FloatingPetWindow");
        SmokeAssert.True(
            floatingType is not null,
            "v1.1 必须提供同进程原生 WPF FloatingPetWindow");

        var panelType = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.AssistantPetPanel");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        var floatingMode = panelType!.GetProperty(
            "IsFloatingMode",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(
            floatingMode?.PropertyType == typeof(bool),
            "AssistantPetPanel 必须提供 IsFloatingMode 以复用同一角色渲染器");

        var floatRequested = panelType.GetEvent(
            "FloatRequested",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(
            floatRequested is not null,
            "侧栏桌宠必须通过只读 UI 事件请求悬浮模式");

        foreach (var forbidden in new[] { "Approve", "Reject", "CreateTask", "CancelTask", "Save", "Connect" })
        {
            var exposed = floatingType!
                .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Any(method => method.Name.Contains(forbidden, StringComparison.OrdinalIgnoreCase));
            SmokeAssert.True(
                !exposed,
                $"FloatingPetWindow 不得暴露业务写入方法 {forbidden}");
        }
    }

    private static void VerifyResourceMonitorContract()
    {
        var desktopAssembly = typeof(ShellViewModel).Assembly;
        var samplerType = desktopAssembly.GetType(
            "PicotooPet.Desktop.Services.WindowsResourceSampler");
        SmokeAssert.True(
            samplerType is not null,
            "v1.1 必须提供本地 WindowsResourceSampler，不能继续展示伪造百分比");

        var sampleMethod = samplerType!.GetMethod(
            "Sample",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(sampleMethod is not null, "WindowsResourceSampler 必须公开 Sample");

        var snapshotType = desktopAssembly.GetType(
            "PicotooPet.Desktop.Services.WindowsResourceSnapshot");
        SmokeAssert.True(snapshotType is not null, "缺少 WindowsResourceSnapshot");
        SmokeAssert.True(
            sampleMethod!.ReturnType == snapshotType,
            "Sample 返回值必须是有界只读 WindowsResourceSnapshot");
    }

    private static void VerifyHomeResourceProjectionContract()
    {
        var viewModelType = typeof(OperatorHomePageViewModel);
        foreach (var propertyName in new[]
                 {
                     "CpuPercent",
                     "MemoryPercent",
                     "DiskPercent",
                     "CpuText",
                     "MemoryText",
                     "DiskText",
                 })
        {
            SmokeAssert.True(
                viewModelType.GetProperty(propertyName, BindingFlags.Public | BindingFlags.Instance) is not null,
                $"首页资源监控缺少属性 {propertyName}");
        }

        var updateMethod = viewModelType.GetMethod(
            "UpdateResourceSnapshot",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(
            updateMethod is not null,
            "首页必须通过独立只读入口更新资源监控，不得改写 Session 快照");
    }

    private static void VerifyAnimationLifecycleContract()
    {
        var panelType = typeof(ShellViewModel).Assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.AssistantPetPanel");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        var visibilityHandler = panelType!.GetMethod(
            "PetSurface_IsVisibleChanged",
            BindingFlags.NonPublic | BindingFlags.Instance);
        SmokeAssert.True(
            visibilityHandler is not null,
            "桌宠必须在不可见时暂停动画计时器，避免后台持续占用 CPU");
    }
}
