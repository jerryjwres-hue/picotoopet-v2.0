using System.Reflection;
using System.Runtime.CompilerServices;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v1.3 茅台 Q 版分层桌宠合同，防止再次退化为矢量占位角色。</summary>
internal static class InteractivePetV13SmokeTests
{
    /// <summary>在常规 WPF smoke 前验证茅台分层资产、行为序列与业务只读边界。</summary>
    [ModuleInitializer]
    public static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Contains(
                "--expect-task-center-legacy-binding-failure",
                StringComparer.Ordinal))
        {
            return;
        }

        VerifyLayeredRigContract();
        VerifySequenceContract();
        VerifyPresentationBoundary();
    }

    private static void VerifyLayeredRigContract()
    {
        var assembly  = typeof(ShellViewModel).Assembly;
        var rigType   = assembly.GetType("PicotooPet.Desktop.Views.Controls.MaotaiPetRig");
        var panelType = assembly.GetType("PicotooPet.Desktop.Views.Controls.AssistantPetPanel");

        SmokeAssert.True(rigType is not null, "v1.3 必须提供 MaotaiPetRig");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        foreach (var propertyName in new[]
                 {
                     "Body",
                     "Head",
                     "Tail",
                     "LeftPaw",
                     "RightPaw",
                     "Laptop",
                     "EyesOpen",
                     "EyesHalf",
                     "EyesClosed",
                     "BrowsFocused",
                     "BrowsAnnoyed",
                     "MouthHappy",
                     "MouthTired",
                     "MouthAnnoyed",
                 })
        {
            SmokeAssert.True(
                rigType!.GetProperty(
                    propertyName,
                    BindingFlags.Public | BindingFlags.Static) is not null,
                $"MaotaiPetRig 缺少 {propertyName} 资源入口");
        }

        foreach (var fieldName in new[]
                 {
                     "MaotaiBody",
                     "MaotaiHead",
                     "MaotaiTail",
                     "LeftPaw",
                     "RightPaw",
                     "FaceEyes",
                     "FaceBrows",
                     "FaceMouth",
                 })
        {
            SmokeAssert.True(
                panelType!.GetField(
                    fieldName,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not null,
                $"v1.3 Q版分层桌宠缺少 {fieldName}");
        }
    }

    private static void VerifySequenceContract()
    {
        var assembly       = typeof(ShellViewModel).Assembly;
        var controllerType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetBehaviorSequenceController");
        var sequenceType   = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetBehaviorSequence");
        var stepType       = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetSequenceStep");

        SmokeAssert.True(controllerType is not null, "v1.3 必须提供 PetBehaviorSequenceController");
        SmokeAssert.True(sequenceType is not null, "v1.3 必须提供 PetBehaviorSequence");
        SmokeAssert.True(stepType is not null, "v1.3 必须提供 PetSequenceStep");

        var nextMethod = controllerType!.GetMethod(
            "NextSequence",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(nextMethod is not null, "PetBehaviorSequenceController 必须公开 NextSequence");
        SmokeAssert.True(nextMethod!.ReturnType == sequenceType, "NextSequence 必须返回 PetBehaviorSequence");

        var returnProperty = sequenceType!.GetProperty(
            "ReturnsToLatestBaseState",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(returnProperty?.PropertyType == typeof(bool), "行为序列必须声明回到最新基础状态");
    }

    private static void VerifyPresentationBoundary()
    {
        var assembly       = typeof(ShellViewModel).Assembly;
        var controllerType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetBehaviorSequenceController");

        SmokeAssert.True(controllerType is not null, "v1.3 行为序列控制器不存在");

        foreach (var forbidden in new[]
                 {
                     "Approve",
                     "Reject",
                     "CreateTask",
                     "CancelTask",
                     "Save",
                     "Connect",
                 })
        {
            var exposed = controllerType!
                .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Any(method => method.Name.Contains(forbidden, StringComparison.OrdinalIgnoreCase));
            SmokeAssert.True(!exposed, $"桌宠序列控制器不得暴露业务写入方法 {forbidden}");
        }
    }
}
