using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Input;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证真正 FloatingPetWindow 拖动入口与 V2 Motion Engine 的冻结/释放/吸附站稳链路。</summary>
internal static class MaotaiFloatingDragLifecycleV2SmokeTests
{
    private static readonly Type PanelType = typeof(AssistantPetPanel);
    private static readonly Type WindowType = typeof(FloatingPetWindow);

    public static void Run() => RunOnSta(() =>
    {
        var failures = new List<string>();
        RunCheck(failures, VerifyPanelDragLifecycleSettlesBeforeAutonomy);
        RunCheck(failures, VerifyActualWindowDragHandlerCoordinatesPet);
        RunCheck(failures, VerifyEdgeSnapReturnsSettleSignal);

        if (failures.Count > 0)
        {
            throw new InvalidOperationException(
                "Maotai floating drag lifecycle v2 smoke failed:\n - " +
                string.Join("\n - ", failures));
        }
    });

    private static void VerifyPanelDragLifecycleSettlesBeforeAutonomy()
    {
        var panel = new AssistantPetPanel { IsFloatingMode = true };
        SetEnumField(panel, "_activeMode", "Resting");
        SetField(panel, "_maotaiRigReady", true);

        var begin = RequirePanelMethod("BeginFloatingWindowDrag", Type.EmptyTypes);
        var end = RequirePanelMethod("EndFloatingWindowDrag", [typeof(bool)]);
        var build = RequirePanelMethod("BuildMaotaiMotionInput", [typeof(double)]);

        begin.Invoke(panel, null);
        Assert(ReadField<bool>(panel, "_isDragging"),
            "真实悬浮窗开始拖动后，FloatingPet 没有进入 Drag 输入状态");
        var draggingInput = build.Invoke(panel, [1.0 / 60.0])
            ?? throw new InvalidOperationException("拖动中的 BuildMaotaiMotionInput 没有输出");
        Assert(string.Equals(ReadProperty(draggingInput, "Interaction").ToString(), "Drag", StringComparison.Ordinal),
            "悬浮窗拖动没有进入 MotionInput.Drag，Engine 无法冻结 locomotion");

        end.Invoke(panel, [false]);
        Assert(!ReadField<bool>(panel, "_isDragging"),
            "悬浮窗松手后 Drag 状态没有释放");
        var unsnappedSettle = ReadField<double>(panel, "_maotaiFloatingSettleSeconds");
        Assert(unsnappedSettle >= 0.18 && unsnappedSettle <= 0.60,
            $"普通松手缺少短站稳窗口；settle={unsnappedSettle:F3}s");

        var settleInput = build.Invoke(panel, [1.0 / 60.0])
            ?? throw new InvalidOperationException("松手后的 BuildMaotaiMotionInput 没有输出");
        Assert(string.Equals(ReadOptionalProperty(settleInput, "AutonomousState")?.ToString(), "Land", StringComparison.Ordinal),
            "拖动释放后没有先进入短 Land/站稳 Pose，就会立刻恢复自主走跑");
        Assert(!Convert.ToBoolean(ReadProperty(settleInput, "WantsRun"), System.Globalization.CultureInfo.InvariantCulture),
            "拖动释放站稳阶段禁止立刻恢复 Run");

        // Edge snap should keep the pet stable slightly longer than a normal release.
        begin.Invoke(panel, null);
        end.Invoke(panel, [true]);
        var snappedSettle = ReadField<double>(panel, "_maotaiFloatingSettleSeconds");
        Assert(snappedSettle > unsnappedSettle + 0.05,
            $"边缘吸附完成后没有额外稳定时间；normal={unsnappedSettle:F3}, snapped={snappedSettle:F3}");

        // Settle must have a bounded exit and return control to autonomous behavior.
        for (var frame = 0; frame < 40; frame++)
        {
            build.Invoke(panel, [0.05]);
        }
        Assert(ReadField<double>(panel, "_maotaiFloatingSettleSeconds") <= 0.001,
            "拖动/吸附站稳没有退出条件，可能永久阻塞自主行为");
    }

    private static void VerifyActualWindowDragHandlerCoordinatesPet()
    {
        using var viewModel = ShellViewModel.CreateForSmokeTest(ControlCenterCapabilities.Legacy22);
        var window = new FloatingPetWindow(viewModel);
        try
        {
            var pet = window.FindName("FloatingPet") as AssistantPetPanel
                ?? throw new InvalidOperationException("FloatingPetWindow 没有实际复用 AssistantPetPanel");
            SetEnumField(pet, "_activeMode", "Resting");
            SetField(pet, "_maotaiRigReady", true);

            var handler = WindowType.GetMethod(
                "DragHandle_MouseLeftButtonDown",
                BindingFlags.Instance | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("FloatingPetWindow 缺少真实拖动 handle handler");
            var args = new MouseButtonEventArgs(
                Mouse.PrimaryDevice,
                Environment.TickCount,
                MouseButton.Left)
            {
                RoutedEvent = UIElement.MouseLeftButtonDownEvent,
            };

            // A synthetic left-button-down drives the actual handler. DragMove is expected to throw when the
            // smoke window is not shown; the production finally-path must still release Drag and schedule settle.
            handler.Invoke(window, [window, args]);

            Assert(!ReadField<bool>(pet, "_isDragging"),
                "FloatingPetWindow 拖动 handler 退出后没有释放 Pet Drag 状态");
            var settle = ReadField<double>(pet, "_maotaiFloatingSettleSeconds");
            Assert(settle > 0.0,
                "真实 FloatingPetWindow 拖动 handler 没有把拖动生命周期交给 FloatingPet；Engine 的 Drag 冻结实际不会被用户窗口拖动触发");
        }
        finally
        {
            window.Close();
        }
    }

    private static void VerifyEdgeSnapReturnsSettleSignal()
    {
        var method = WindowType.GetMethod(
            "SnapToNearestEdge",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("FloatingPetWindow 缺少 SnapToNearestEdge");
        Assert(method.ReturnType == typeof(bool),
            "SnapToNearestEdge 仍然返回 void；窗口层无法告诉 Motion Engine 吸附是否发生，也就无法执行吸附后额外站稳");
    }

    private static MethodInfo RequirePanelMethod(string name, Type[] parameters) =>
        PanelType.GetMethod(
            name,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            binder: null,
            types: parameters,
            modifiers: null)
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少 {name}({string.Join(",", parameters.Select(type => type.Name))})");

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static object? ReadOptionalProperty(object target, string name)
    {
        var property = target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");
        return property.GetValue(target);
    }

    private static T ReadField<T>(object target, string name)
    {
        var value = RequirePanelField(name).GetValue(target);
        return value is T typed
            ? typed
            : throw new InvalidOperationException($"AssistantPetPanel.{name} 不是 {typeof(T).Name}");
    }

    private static void SetEnumField(object target, string fieldName, string value)
    {
        var field = RequirePanelField(fieldName);
        field.SetValue(target, Enum.Parse(field.FieldType, value));
    }

    private static void SetField(object target, string fieldName, object value) =>
        RequirePanelField(fieldName).SetValue(target, value);

    private static FieldInfo RequirePanelField(string name) =>
        PanelType.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少字段 {name}");

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
            throw new InvalidOperationException("Maotai floating drag lifecycle STA smoke failed.", failure);
        }
    }

    private static void RunCheck(List<string> failures, Action check)
    {
        try
        {
            check();
        }
        catch (TargetInvocationException exception) when (exception.InnerException is not null)
        {
            failures.Add(exception.InnerException.Message);
        }
        catch (Exception exception)
        {
            failures.Add(exception.Message);
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
