using System.Reflection;
using System.Threading;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 V2 的运行时所有权：旧低频调度器/呼吸/错误抖动不得再修改 V2 父级 Transform，真实 RoutedEvent 和 Rig 输出必须进入 V2。</summary>
internal static class MaotaiRuntimeOwnershipV2SmokeTests
{
    private static readonly Type PanelType = typeof(AssistantPetPanel);

    public static void Run() => RunOnSta(() =>
    {
        VerifyLegacyFrameTickCannotMoveV2Parent();
        VerifyLegacyBreathingCannotScaleV2Parent();
        VerifyLegacyErrorShakeCannotAnimateV2Parent();
        VerifyDoubleClickRoutesIntoV2MotionEngine();
        VerifyRuntimeRigRequiresWorkProps();
        VerifyChestPoseReachesVisibleLayer();
        VerifyWorkingPropsReachVisibleLayers();
    });

    private static void VerifyLegacyFrameTickCannotMoveV2Parent()
    {
        var sleepingPanel = new AssistantPetPanel();
        SetField(sleepingPanel, "_maotaiRigReady", true);
        SetEnumField(sleepingPanel, "_activeMode", "Offline");
        SetField(sleepingPanel, "_frameIndex", 0);
        var sleepingScale = GetField<ScaleTransform>(sleepingPanel, "PetScale");
        sleepingScale.ScaleY = 1.0;

        Invoke(sleepingPanel, "FrameTimer_Tick", null, EventArgs.Empty);
        AssertNear(1.0, sleepingScale.ScaleY,
            "V2 active 时旧 FrameTimer_Tick 仍在阶梯式缩放 PetScale，会形成双动画引擎");

        var errorPanel = new AssistantPetPanel();
        SetField(errorPanel, "_maotaiRigReady", true);
        SetEnumField(errorPanel, "_activeMode", "Error");
        SetField(errorPanel, "_frameIndex", 0);
        var errorTranslate = GetField<TranslateTransform>(errorPanel, "PetTranslate");
        errorTranslate.X = 0.0;

        Invoke(errorPanel, "FrameTimer_Tick", null, EventArgs.Empty);
        AssertNear(0.0, errorTranslate.X,
            "V2 active 时旧 FrameTimer_Tick 仍在移动 PetTranslate，会叠加到连续 Motion Engine");
    }

    private static void VerifyLegacyBreathingCannotScaleV2Parent()
    {
        var panel = new AssistantPetPanel();
        SetField(panel, "_maotaiRigReady", true);
        var scale = GetField<ScaleTransform>(panel, "PetScale");
        scale.ScaleY = 1.234;
        var resting = GetEnumFieldValue(panel, "_activeMode", "Resting");

        Invoke(panel, "StartBreathing", resting);
        AssertNear(1.0, scale.ScaleY,
            "V2 active 时 StartBreathing 必须释放旧父级缩放并归一化，呼吸只能由 Motion Engine 输出");
        Assert(!scale.HasAnimatedProperties,
            "V2 active 时 PetScale 不得保留旧 WPF breathing animation clock");
    }

    private static void VerifyLegacyErrorShakeCannotAnimateV2Parent()
    {
        var panel = new AssistantPetPanel();
        SetField(panel, "_maotaiRigReady", true);
        var translate = GetField<TranslateTransform>(panel, "PetTranslate");
        translate.BeginAnimation(TranslateTransform.XProperty, null);
        translate.X = 0.0;

        Invoke(panel, "AnimateErrorShake");
        Assert(!translate.HasAnimatedProperties,
            "V2 active 时旧 AnimateErrorShake 不得给 PetTranslate 挂第二套 WPF 动画");
        AssertNear(0.0, translate.X,
            "V2 active 时错误状态位移必须由 Motion Engine 决定，而不是旧父级 shake");
    }

    private static void VerifyDoubleClickRoutesIntoV2MotionEngine()
    {
        var panel = new AssistantPetPanel();
        SetField(panel, "_maotaiRigReady", true);
        SetField(panel, "_maotaiJumpRequested", false);
        SetEnumField(panel, "_maotaiInteraction", "None");

        var args = new MouseButtonEventArgs(Mouse.PrimaryDevice, Environment.TickCount, MouseButton.Left)
        {
            RoutedEvent = Control.MouseDoubleClickEvent,
        };

        // Raise the actual control event so XAML handlers and partial-class handlers compete exactly as in the UI.
        panel.RaiseEvent(args);

        Assert(GetValue<bool>(panel, "_maotaiJumpRequested"),
            "V2 active 时真实 MouseDoubleClick RoutedEvent 没有请求 Motion Engine jump；旧 XAML handler 把事件吃掉后桌面 UI 无法触发跳跃");
        Assert(string.Equals(GetValue<object>(panel, "_maotaiInteraction").ToString(), "Celebrate", StringComparison.Ordinal),
            "V2 active 时真实 MouseDoubleClick RoutedEvent 没有写入 Celebrate interaction");
    }

    private static void VerifyRuntimeRigRequiresWorkProps()
    {
        var field = PanelType.GetField(
            "MaotaiRequiredRigAssets",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("AssistantPetPanel 缺少 V2 runtime required-rig 集合");
        var required = field.GetValue(null) as string[]
            ?? throw new InvalidOperationException("V2 runtime required-rig 集合类型异常");

        Assert(Array.IndexOf(required, "laptop.png") >= 0,
            "V2 runtime ready 判定漏掉 laptop.png，会允许空中打字的假完整 Rig 启动");
        Assert(Array.IndexOf(required, "drink.png") >= 0,
            "V2 runtime ready 判定漏掉 drink.png，manifest 与真实运行时完整性不一致");
    }

    private static void VerifyChestPoseReachesVisibleLayer()
    {
        var harness = CreateRendererHarness();
        var pose = CreatePose(
            harness.RendererType.Assembly,
            motionState: "Idle",
            chestX: 4.25,
            chestY: -7.50,
            chestRotation: 8.50);

        harness.Apply.Invoke(harness.Renderer, [pose]);

        var chestProperty = harness.Visuals.GetType().GetProperty(
            "Chest",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiRasterVisuals 没有 Chest 可动绑定；PoseFrame.Chest 当前没有上屏路径");
        var chestPart = chestProperty.GetValue(harness.Visuals)
            ?? throw new InvalidOperationException("MaotaiRasterVisuals.Chest 为空");
        var translate = ReadPartTransform<TranslateTransform>(chestPart, "Translate");
        var rotate = ReadPartTransform<RotateTransform>(chestPart, "Rotate");

        AssertNear(4.25, translate.X,
            "PoseFrame.Chest.X 没有实际进入胸毛可见图层");
        AssertNear(-7.50, translate.Y,
            "PoseFrame.Chest.Y 没有实际进入胸毛可见图层");
        AssertNear(8.50, rotate.Angle,
            "PoseFrame.Chest.RotationDeg 没有实际进入胸毛可见图层");
    }

    private static void VerifyWorkingPropsReachVisibleLayers()
    {
        var harness = CreateRendererHarness();
        var laptop = GetField<Image>(harness.Panel, "MaotaiV2Laptop");
        var drink = GetField<Image>(harness.Panel, "MaotaiV2Drink");

        var workPose = CreatePose(harness.RendererType.Assembly, "WorkTyping", 0.0, -4.0, 0.0);
        harness.Apply.Invoke(harness.Renderer, [workPose]);
        Assert(laptop.Opacity >= 0.99,
            "WorkTyping 已经驱动双爪键盘 IK，但真实 laptop 图层仍不可见，形成空中打字");
        Assert(drink.Opacity >= 0.99,
            "Working 道具 drink 已加载但没有进入真实 Renderer 可见链");

        var idlePose = CreatePose(harness.RendererType.Assembly, "Idle", 0.0, -4.0, 0.0);
        harness.Apply.Invoke(harness.Renderer, [idlePose]);
        Assert(laptop.Opacity <= 0.01 && drink.Opacity <= 0.01,
            "退出工作状态后 laptop/drink 必须由同一 Renderer 隐藏，不能留下陈旧工作场景");
    }

    private static RendererHarness CreateRendererHarness()
    {
        var panel = new AssistantPetPanel();
        var buildVisuals = PanelType.GetMethod(
            "BuildMaotaiRasterVisuals",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("AssistantPetPanel 缺少 BuildMaotaiRasterVisuals");
        var visuals = buildVisuals.Invoke(panel, null)
            ?? throw new InvalidOperationException("BuildMaotaiRasterVisuals 没有返回可见层集合");
        var rendererType = PanelType.Assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer",
            throwOnError: true)!;
        var renderer = Activator.CreateInstance(rendererType, visuals)
            ?? throw new InvalidOperationException("无法创建 MaotaiRasterRenderer");
        var apply = rendererType.GetMethod(
            "Apply",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiRasterRenderer 缺少 Apply");

        return new RendererHarness(panel, visuals, rendererType, renderer, apply);
    }

    private static object CreatePose(
        Assembly assembly,
        string motionState,
        double chestX,
        double chestY,
        double chestRotation)
    {
        var poseType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiPoseFrame",
            throwOnError: true)!;
        var boneType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBonePose",
            throwOnError: true)!;
        var motionStateType = assembly.GetType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState",
            throwOnError: true)!;
        var pose = Activator.CreateInstance(poseType)
            ?? throw new InvalidOperationException("无法创建 MaotaiPoseFrame");
        var chest = Activator.CreateInstance(
            boneType,
            [chestX, chestY, chestRotation, 1.0, 1.0])
            ?? throw new InvalidOperationException("无法创建 Chest MaotaiBonePose");
        var stableState = Enum.Parse(motionStateType, motionState);

        RequireProperty(poseType, "Chest").SetValue(pose, chest);
        RequireProperty(poseType, "MotionState").SetValue(pose, stableState);
        // Synthetic renderer fixtures model a completed stable frame, not the first frame of a graph transition.
        RequireProperty(poseType, "PreviousMotionState").SetValue(pose, stableState);
        RequireProperty(poseType, "MotionTransitionBlend").SetValue(pose, 1.0);
        RequireProperty(poseType, "FacingSign").SetValue(pose, 1);
        return pose;
    }

    private static T ReadPartTransform<T>(object part, string propertyName) where T : class
    {
        var property = part.GetType().GetProperty(
            propertyName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"MaotaiRasterPart 缺少 {propertyName}");
        return property.GetValue(part) as T
            ?? throw new InvalidOperationException($"MaotaiRasterPart.{propertyName} 不是 {typeof(T).Name}");
    }

    private static PropertyInfo RequireProperty(Type type, string propertyName) =>
        type.GetProperty(propertyName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"{type.Name} 缺少属性 {propertyName}");

    private static void RunOnSta(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (failure is not null)
        {
            throw new InvalidOperationException("Maotai V2 runtime ownership smoke failed.", failure);
        }
    }

    private static object GetEnumFieldValue(object target, string fieldName, string value)
    {
        var field = RequireField(fieldName);
        return Enum.Parse(field.FieldType, value);
    }

    private static void SetEnumField(object target, string fieldName, string value)
    {
        var field = RequireField(fieldName);
        field.SetValue(target, Enum.Parse(field.FieldType, value));
    }

    private static void SetField(object target, string fieldName, object value) =>
        RequireField(fieldName).SetValue(target, value);

    private static T GetValue<T>(object target, string fieldName)
    {
        var value = RequireField(fieldName).GetValue(target);
        return value is T typed
            ? typed
            : throw new InvalidOperationException($"{fieldName} 不是 {typeof(T).Name}");
    }

    private static T GetField<T>(object target, string fieldName) where T : class =>
        RequireField(fieldName).GetValue(target) as T
        ?? throw new InvalidOperationException($"{fieldName} 不是 {typeof(T).Name}");

    private static FieldInfo RequireField(string fieldName) =>
        PanelType.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少字段 {fieldName}");

    private static void Invoke(object target, string methodName, params object?[] args)
    {
        var method = PanelType.GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"AssistantPetPanel 缺少方法 {methodName}");
        method.Invoke(target, args);
    }

    private static void AssertNear(double expected, double actual, string message)
    {
        if (!double.IsFinite(actual) || Math.Abs(expected - actual) > 0.000001)
        {
            throw new InvalidOperationException($"{message}；expected={expected:F3}, actual={actual:F3}");
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private readonly record struct RendererHarness(
        AssistantPetPanel Panel,
        object Visuals,
        Type RendererType,
        object Renderer,
        MethodInfo Apply);
}
