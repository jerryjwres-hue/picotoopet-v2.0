using System.Reflection;
using System.Threading;
using System.Windows.Input;
using System.Windows.Media;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 V2 的运行时所有权：旧低频调度器/呼吸/错误抖动不得再修改 V2 父级 Transform，旧 XAML 交互入口必须进入 V2。</summary>
internal static class MaotaiRuntimeOwnershipV2SmokeTests
{
    private static readonly Type PanelType = typeof(AssistantPetPanel);

    public static void Run() => RunOnSta(() =>
    {
        VerifyLegacyFrameTickCannotMoveV2Parent();
        VerifyLegacyBreathingCannotScaleV2Parent();
        VerifyLegacyErrorShakeCannotAnimateV2Parent();
        VerifyDoubleClickRoutesIntoV2MotionEngine();
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
            RoutedEvent = System.Windows.Controls.Control.MouseDoubleClickEvent,
        };

        Invoke(panel, "PetSurface_MouseDoubleClick", panel, args);

        Assert(GetValue<bool>(panel, "_maotaiJumpRequested"),
            "V2 active 时 XAML 双击入口没有请求 Motion Engine jump；旧 handler 把事件吃掉后真实 UI 无法触发跳跃");
        Assert(string.Equals(GetValue<object>(panel, "_maotaiInteraction").ToString(), "Celebrate", StringComparison.Ordinal),
            "V2 active 时 XAML 双击入口没有写入 Celebrate interaction");
    }

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
}
