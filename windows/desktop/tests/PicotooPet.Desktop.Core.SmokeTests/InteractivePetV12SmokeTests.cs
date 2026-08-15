using System.Reflection;
using System.Runtime.CompilerServices;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v1.2 行为调度、表情层、悬浮交互与整体 Simple Mode 视觉升级合同。</summary>
internal static class InteractivePetV12SmokeTests
{
    /// <summary>在常规 WPF smoke 前验证 v1.2 展示层存在，并继续保持业务只读边界。</summary>
    [ModuleInitializer]
    public static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Contains(
                "--expect-task-center-legacy-binding-failure",
                StringComparer.Ordinal))
        {
            return;
        }

        VerifyBehaviorControllerContract();
        VerifyBehaviorSequenceContract();
        VerifyEmotionLayerContract();
        VerifyFloatingInteractionContract();
        VerifyVisualPolishContract();
    }

    private static void VerifyBehaviorControllerContract()
    {
        var desktopAssembly = typeof(ShellViewModel).Assembly;
        var controllerType  = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetBehaviorController");
        var frameType       = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetBehaviorFrame");
        var emotionType     = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetEmotion");
        var actionType      = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.PetMicroAction");

        SmokeAssert.True(controllerType is not null, "v1.2 必须提供独立 PetBehaviorController");
        SmokeAssert.True(frameType is not null, "v1.2 必须提供 PetBehaviorFrame");
        SmokeAssert.True(emotionType?.IsEnum == true, "v1.2 必须提供 PetEmotion 枚举");
        SmokeAssert.True(actionType?.IsEnum == true, "v1.2 必须提供 PetMicroAction 枚举");

        var nextMethod = controllerType!.GetMethod(
            "Next",
            BindingFlags.Public | BindingFlags.Instance);
        SmokeAssert.True(nextMethod is not null, "PetBehaviorController 必须公开 Next 行为调度入口");
        SmokeAssert.True(nextMethod!.ReturnType == frameType, "Next 必须返回 PetBehaviorFrame");

        foreach (var expected in new[]
                 {
                     "LookAround",
                     "Stretch",
                     "Yawn",
                     "LickNose",
                     "CuriousTilt",
                     "HappyBounce",
                     "FocusGlance",
                 })
        {
            SmokeAssert.True(
                Enum.GetNames(actionType!).Contains(expected, StringComparer.Ordinal),
                $"PetMicroAction 缺少 {expected}");
        }

        foreach (var expected in new[]
                 {
                     "Calm",
                     "Focused",
                     "Happy",
                     "Curious",
                     "Sleepy",
                     "Concerned",
                 })
        {
            SmokeAssert.True(
                Enum.GetNames(emotionType!).Contains(expected, StringComparer.Ordinal),
                $"PetEmotion 缺少 {expected}");
        }

        var panelType = desktopAssembly.GetType(
            "PicotooPet.Desktop.Views.Controls.AssistantPetPanel");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        var controllerField = panelType!.GetField(
            "_behaviorController",
            BindingFlags.NonPublic | BindingFlags.Instance);
        SmokeAssert.True(
            controllerField?.FieldType == controllerType,
            "AssistantPetPanel 必须组合 PetBehaviorController，而不是继续堆叠状态 if/else");

        var applyFrameMethod = panelType.GetMethod(
            "ApplyBehaviorFrame",
            BindingFlags.NonPublic | BindingFlags.Instance);
        SmokeAssert.True(applyFrameMethod is not null, "AssistantPetPanel 必须统一应用行为帧");

        foreach (var forbidden in new[] { "Approve", "Reject", "CreateTask", "CancelTask", "Save", "Connect" })
        {
            var exposed = controllerType
                .GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly)
                .Any(method => method.Name.Contains(forbidden, StringComparison.OrdinalIgnoreCase));
            SmokeAssert.True(!exposed, $"PetBehaviorController 不得暴露业务写入方法 {forbidden}");
        }
    }

    private static void VerifyBehaviorSequenceContract()
    {
        var controller = new PetBehaviorController(seed: 17);
        var actions = Enumerable.Range(0, 72)
            .Select(_ => controller.Next(AssistantPetMode.Resting, allowMicroAction: true).Action)
            .Where(action => action != PetMicroAction.None)
            .ToArray();

        SmokeAssert.True(actions.Length >= 4, "v1.2 休息状态应在有界冷却后产生随机微动作");
        SmokeAssert.True(
            actions.Distinct().Count() >= 3,
            "v1.2 微动作序列不能长期退化为同一机械循环");

        var suppressed = controller.Next(AssistantPetMode.Resting, allowMicroAction: false);
        SmokeAssert.True(
            suppressed.Action == PetMicroAction.None,
            "指针/拖拽交互期间随机微动作必须让位给用户交互");
    }

    private static void VerifyEmotionLayerContract()
    {
        var panelType = typeof(ShellViewModel).Assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.AssistantPetPanel");
        SmokeAssert.True(panelType is not null, "AssistantPetPanel 不存在");

        foreach (var fieldName in new[]
                 {
                     "LeftBrow",
                     "RightBrow",
                     "LeftBlush",
                     "RightBlush",
                     "EmotionGlyph",
                 })
        {
            SmokeAssert.True(
                panelType!.GetField(
                    fieldName,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not null,
                $"v1.2 表情层缺少 {fieldName}");
        }
    }

    private static void VerifyFloatingInteractionContract()
    {
        var floatingType = typeof(ShellViewModel).Assembly.GetType(
            "PicotooPet.Desktop.Views.FloatingPetWindow");
        SmokeAssert.True(floatingType is not null, "FloatingPetWindow 不存在");

        SmokeAssert.True(
            floatingType!.GetField(
                "SizeButton",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not null,
            "v1.2 悬浮桌宠必须提供有界尺寸切换入口");
        SmokeAssert.True(
            floatingType.GetMethod(
                "SnapToNearestEdge",
                BindingFlags.NonPublic | BindingFlags.Instance) is not null,
            "v1.2 悬浮桌宠必须在拖动后支持屏幕边缘吸附");
        SmokeAssert.True(
            floatingType.GetMethod(
                "CyclePetSize",
                BindingFlags.NonPublic | BindingFlags.Instance) is not null,
            "v1.2 悬浮桌宠必须使用有界预设尺寸而非任意缩放");
    }

    private static void VerifyVisualPolishContract()
    {
        var shellType = typeof(PicotooPet.Desktop.Views.ShellWindow);
        foreach (var fieldName in new[] { "HeaderModePill", "HeaderStatusDot" })
        {
            SmokeAssert.True(
                shellType.GetField(
                    fieldName,
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not null,
                $"v1.2 Shell 视觉层缺少 {fieldName}");
        }

        var homeType = typeof(PicotooPet.Desktop.Views.Pages.OperatorHomePage);
        SmokeAssert.True(
            homeType.GetField(
                "HomeGreetingStrip",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) is not null,
            "v1.2 首页必须提供统一的状态摘要视觉条");
    }
}
