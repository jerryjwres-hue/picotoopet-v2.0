using System.Reflection;
using System.Threading;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 v2 自主行为与悬浮桌宠的真实产品入口，避免“引擎支持但 UI 永远不请求”。</summary>
internal static class MaotaiAutonomousFloatingV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;
    private static readonly Type PanelType = typeof(AssistantPetPanel);

    public static void Run() => RunOnSta(() =>
    {
        var failures = new List<string>();
        RunCheck(failures, VerifyFloatingModeExpandsRealMotionStage);
        RunCheck(failures, VerifyDragFreezesLocomotion);
        RunCheck(failures, VerifyAutonomyFlowsThroughRealInputBuilder);
        RunCheck(failures, VerifyAutonomyHasMemoryAndBoundedDuration);

        if (failures.Count > 0)
        {
            throw new InvalidOperationException(
                "Maotai autonomous/floating v2 smoke failed:\n - " +
                string.Join("\n - ", failures));
        }
    });

    private static void VerifyFloatingModeExpandsRealMotionStage()
    {
        var panel = new AssistantPetPanel();
        SetEnumField(panel, "_activeMode", "Resting");
        SetField(panel, "_isDragging", false);

        panel.IsFloatingMode = false;
        var sidebarInput = InvokeBuildInput(panel, 0.0);
        var sidebarMin = ReadDouble(sidebarInput, "StageMinX");
        var sidebarMax = ReadDouble(sidebarInput, "StageMaxX");

        panel.IsFloatingMode = true;
        var floatingInput = InvokeBuildInput(panel, 0.0);
        var floatingMin = ReadDouble(floatingInput, "StageMinX");
        var floatingMax = ReadDouble(floatingInput, "StageMaxX");

        var sidebarSpan = sidebarMax - sidebarMin;
        var floatingSpan = floatingMax - floatingMin;
        Assert(sidebarSpan > 0.0, "侧栏 Motion Stage 范围非法");
        Assert(floatingSpan >= sidebarSpan + 24.0,
            $"悬浮桌宠没有获得更大的真实 Motion Stage；sidebar={sidebarSpan:F1}, floating={floatingSpan:F1}");
        Assert(floatingMin < sidebarMin && floatingMax > sidebarMax,
            "悬浮模式必须同时扩展左右活动边界，而不是只改卡片外观");
    }

    private static void VerifyDragFreezesLocomotion()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = engineType.GetMethod("Update", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, 91, 36.0)
            ?? throw new InvalidOperationException("无法创建 MaotaiMotionEngine");

        // First establish real walking momentum so a drag test cannot pass merely because the pet started stationary.
        var walking = CreateInput(
            baseState: "Resting",
            interaction: "None",
            stageMinX: 18.0,
            stageMaxX: 150.0,
            targetX: 136.0,
            wantsRun: false,
            wantsJump: false);
        for (var frame = 0; frame < 24; frame++)
        {
            update.Invoke(engine, [1.0 / 60.0, walking]);
        }

        var beforeDrag = ReadDouble(engine, "PositionX");
        var dragging = CreateInput(
            baseState: "Resting",
            interaction: "Drag",
            stageMinX: 18.0,
            stageMaxX: 150.0,
            targetX: 136.0,
            wantsRun: false,
            wantsJump: false);
        for (var frame = 0; frame < 90; frame++)
        {
            update.Invoke(engine, [1.0 / 60.0, dragging]);
        }

        var afterDrag = ReadDouble(engine, "PositionX");
        Assert(Math.Abs(afterDrag - beforeDrag) <= 0.05,
            $"Drag 期间内部 locomotion 仍在自主移动；before={beforeDrag:F3}, after={afterDrag:F3}");
    }

    private static void VerifyAutonomyFlowsThroughRealInputBuilder()
    {
        var panel = new AssistantPetPanel { IsFloatingMode = true };
        SetEnumField(panel, "_activeMode", "Resting");
        SetField(panel, "_isDragging", false);

        var method = PanelType.GetMethod(
            "BuildMaotaiMotionInput",
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            types: [typeof(double)],
            modifiers: null)
            ?? throw new InvalidOperationException(
                "真实 BuildMaotaiMotionInput 仍没有 deltaTime，自主行为无法在唯一 Render Loop 中有记忆地推进");

        var sawMovingTarget = false;
        var sawRun = false;
        var sawSit = false;
        var sawLieDown = false;
        var previousTarget = double.NaN;
        var targetChanges = 0;

        for (var frame = 0; frame < 7200; frame++)
        {
            var input = method.Invoke(panel, [0.05])
                ?? throw new InvalidOperationException("BuildMaotaiMotionInput 没有返回输入");
            var target = ReadDouble(input, "TargetX");
            var stageMin = ReadDouble(input, "StageMinX");
            var stageMax = ReadDouble(input, "StageMaxX");
            Assert(target >= stageMin - 0.001 && target <= stageMax + 0.001,
                "自主行为 TargetX 越过真实 Motion Stage");

            if (Math.Abs(target - 72.0) > 4.0)
            {
                sawMovingTarget = true;
            }
            if (!double.IsNaN(previousTarget) && Math.Abs(target - previousTarget) > 2.0)
            {
                targetChanges++;
            }
            previousTarget = target;
            sawRun |= ReadBool(input, "WantsRun");

            var autonomousState = ReadOptionalEnumName(input, "AutonomousState");
            sawSit |= string.Equals(autonomousState, "Sit", StringComparison.Ordinal);
            sawLieDown |= string.Equals(autonomousState, "LieDown", StringComparison.Ordinal);
        }

        Assert(sawMovingTarget && targetChanges >= 2,
            "悬浮 Resting 仍固定 TargetX=72；真实产品没有自主散步入口");
        Assert(sawRun,
            "悬浮 Resting 长时间运行从未向 Motion Engine 请求 Run");
        Assert(sawSit && sawLieDown,
            "悬浮 Resting 长时间运行没有把 Sit/LieDown 自主意图送入真实 Motion Engine 输入");
    }

    private static void VerifyAutonomyHasMemoryAndBoundedDuration()
    {
        var controllerType = RequireType(
            "PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAutonomousBehaviorController");
        var update = controllerType.GetMethod(
            "Update",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            binder: null,
            types: [typeof(double), typeof(double), typeof(double), typeof(double), typeof(bool), typeof(bool)],
            modifiers: null)
            ?? throw new InvalidOperationException(
                "MaotaiAutonomousBehaviorController 缺少确定性的 Update(dt,currentX,minX,maxX,floating,enabled)");
        var controller = Activator.CreateInstance(controllerType, 73)
            ?? throw new InvalidOperationException("无法创建自主行为 controller");

        var previousSequence = -1;
        string? previousBehavior = null;
        var elapsedSinceSelection = 0.0;
        var selections = 0;
        var currentX = 72.0;

        for (var frame = 0; frame < 7200; frame++)
        {
            elapsedSinceSelection += 0.05;
            var intent = update.Invoke(controller, [0.05, currentX, 18.0, 150.0, true, true])
                ?? throw new InvalidOperationException("自主行为 controller 没有返回 intent");
            var sequence = ReadInt(intent, "Sequence");
            var behavior = ReadEnumName(intent, "Behavior");
            var target = ReadDouble(intent, "TargetX");
            currentX = target; // simulate arrival so behavior hold time, not locomotion travel, determines the bound.

            if (sequence == previousSequence)
            {
                continue;
            }

            if (previousSequence >= 0)
            {
                Assert(elapsedSinceSelection <= 5.25,
                    $"自主行为缺少最大持续时间；{previousBehavior} 已持续 {elapsedSinceSelection:F2}s");
                Assert(!string.Equals(previousBehavior, behavior, StringComparison.Ordinal),
                    $"自主行为没有 Cooldown/记忆，连续重复选择 {behavior}");
            }

            previousSequence = sequence;
            previousBehavior = behavior;
            elapsedSinceSelection = 0.0;
            selections++;
        }

        Assert(selections >= 8,
            $"自主行为选择次数过少，无法形成自然有记忆循环；selections={selections}");
    }

    private static object InvokeBuildInput(AssistantPetPanel panel, double deltaTime)
    {
        var timed = PanelType.GetMethod(
            "BuildMaotaiMotionInput",
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            types: [typeof(double)],
            modifiers: null);
        if (timed is not null)
        {
            return timed.Invoke(panel, [deltaTime])
                ?? throw new InvalidOperationException("BuildMaotaiMotionInput(double) 没有返回输入");
        }

        var legacy = PanelType.GetMethod(
            "BuildMaotaiMotionInput",
            BindingFlags.Instance | BindingFlags.NonPublic,
            binder: null,
            types: Type.EmptyTypes,
            modifiers: null)
            ?? throw new InvalidOperationException("AssistantPetPanel 缺少 BuildMaotaiMotionInput");
        return legacy.Invoke(panel, null)
            ?? throw new InvalidOperationException("BuildMaotaiMotionInput() 没有返回输入");
    }

    private static object CreateInput(
        string baseState,
        string interaction,
        double stageMinX,
        double stageMaxX,
        double targetX,
        bool wantsRun,
        bool wantsJump)
    {
        var inputType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var baseStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        return Activator.CreateInstance(
            inputType,
            [
                Enum.Parse(baseStateType, baseState),
                0.0,
                0.0,
                false,
                Enum.Parse(interactionType, interaction),
                stageMinX,
                stageMaxX,
                targetX,
                wantsRun,
                wantsJump,
                70.0,
            ]) ?? throw new InvalidOperationException("无法创建 MaotaiMotionInput");
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
            throw new InvalidOperationException(
                "Maotai autonomous/floating v2 STA smoke failed.",
                failure);
        }
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

    private static Type RequireType(string name) =>
        DesktopAssembly.GetType(name, throwOnError: true)!;

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static double ReadDouble(object target, string name) =>
        Convert.ToDouble(ReadProperty(target, name), System.Globalization.CultureInfo.InvariantCulture);

    private static int ReadInt(object target, string name) =>
        Convert.ToInt32(ReadProperty(target, name), System.Globalization.CultureInfo.InvariantCulture);

    private static bool ReadBool(object target, string name) =>
        Convert.ToBoolean(ReadProperty(target, name), System.Globalization.CultureInfo.InvariantCulture);

    private static string ReadEnumName(object target, string name) =>
        ReadProperty(target, name).ToString()
        ?? throw new InvalidOperationException($"{name} 枚举为空");

    private static string? ReadOptionalEnumName(object target, string name)
    {
        var property = target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");
        return property.GetValue(target)?.ToString();
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
