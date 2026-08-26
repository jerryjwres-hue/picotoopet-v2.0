using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结工作动作被真实业务状态打断时的相邻帧连续性。</summary>
internal static class MaotaiInterruptedWorkMoodV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyMidTransitionWorkSettleExitContinuity();
        VerifyMidTransitionTiredExitContinuity();
    }

    /// <summary>中后段 WorkSettle 被 Resting 打断时，Idle 必须从当下部分下沉姿态连续释放。</summary>
    private static void VerifyMidTransitionWorkSettleExitContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = RequireMethod(engineType, "Update");
        var engine = Activator.CreateInstance(engineType, 81, 108.0)
            ?? throw new InvalidOperationException("无法创建工作落位中断 Motion Engine");

        object? settlePose = null;
        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("工作落位中断预热没有输出 PoseFrame");
            var state = ReadProperty(pose, "MotionState")?.ToString();
            var previousState = ReadProperty(pose, "PreviousMotionState")?.ToString();
            var transitionBlend = ReadDouble(pose, "MotionTransitionBlend");
            if (string.Equals(state, "WorkSettle", StringComparison.Ordinal) &&
                string.Equals(previousState, "WorkApproach", StringComparison.Ordinal) &&
                transitionBlend >= 0.79 && transitionBlend <= 0.82)
            {
                settlePose = pose;
                break;
            }
        }

        Assert(settlePose is not null, "工作落位中断测试未捕获到中后段 WorkApproach→WorkSettle");

        var idlePose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
            ?? throw new InvalidOperationException("工作落位中断退出首帧没有输出 PoseFrame");
        var stateAfterInterrupt = ReadProperty(idlePose, "MotionState")?.ToString();
        Assert(string.Equals(stateAfterInterrupt, "Idle", StringComparison.Ordinal),
            $"WorkSettle 被 Resting 打断后应立即回退 Idle；actual={stateAfterInterrupt}");

        var bodyYDelta = Math.Abs(
            ReadPoseDouble(idlePose, "Body", "Y") - ReadPoseDouble(settlePose!, "Body", "Y"));
        var bodyScaleYDelta = Math.Abs(
            ReadPoseDouble(idlePose, "Body", "ScaleY") - ReadPoseDouble(settlePose!, "Body", "ScaleY"));

        Assert(bodyYDelta < 0.75,
            $"中段 WorkSettle→Idle 身体高度不能把部分落位姿态瞬间归零；delta={bodyYDelta:F3}");
        Assert(bodyScaleYDelta < 0.012,
            $"中段 WorkSettle→Idle 纵向缩放不能把部分落位姿态瞬间归零；delta={bodyScaleYDelta:F4}");
    }

    /// <summary>早段 WorkTired 被 Resting 打断时，Recover 必须从当下部分疲劳姿态继续。</summary>
    private static void VerifyMidTransitionTiredExitContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = RequireMethod(engineType, "Update");
        var engine = Activator.CreateInstance(engineType, 83, 108.0)
            ?? throw new InvalidOperationException("无法创建疲劳中断 Motion Engine");

        object? tiredPose = null;
        for (var frame = 0; frame < 960; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("疲劳中断预热没有输出 PoseFrame");
            var state = ReadProperty(pose, "MotionState")?.ToString();
            var previousState = ReadProperty(pose, "PreviousMotionState")?.ToString();
            var transitionBlend = ReadDouble(pose, "MotionTransitionBlend");
            if (string.Equals(state, "WorkTired", StringComparison.Ordinal) &&
                string.Equals(previousState, "WorkTyping", StringComparison.Ordinal) &&
                transitionBlend >= 0.12 && transitionBlend <= 0.18)
            {
                tiredPose = pose;
                break;
            }
        }

        Assert(tiredPose is not null, "疲劳中断测试未捕获到早段 WorkTyping→WorkTired");

        var recoverPose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
            ?? throw new InvalidOperationException("疲劳中断退出首帧没有输出 PoseFrame");
        var stateAfterInterrupt = ReadProperty(recoverPose, "MotionState")?.ToString();
        Assert(string.Equals(stateAfterInterrupt, "Recover", StringComparison.Ordinal),
            $"WorkTired 被 Resting 打断后应立即进入 Recover；actual={stateAfterInterrupt}");

        var bodyYDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "Y") - ReadPoseDouble(tiredPose!, "Body", "Y"));
        var bodyScaleXDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "ScaleX") - ReadPoseDouble(tiredPose!, "Body", "ScaleX"));
        var bodyScaleYDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "ScaleY") - ReadPoseDouble(tiredPose!, "Body", "ScaleY"));

        Assert(bodyYDelta < 0.75,
            $"早段 WorkTired→Recover 身体高度不能跳到完整疲劳端点；delta={bodyYDelta:F3}");
        Assert(bodyScaleXDelta < 0.012,
            $"早段 WorkTired→Recover 横向缩放不能跳到完整疲劳端点；delta={bodyScaleXDelta:F4}");
        Assert(bodyScaleYDelta < 0.012,
            $"早段 WorkTired→Recover 纵向缩放不能跳到完整疲劳端点；delta={bodyScaleYDelta:F4}");
    }

    private static object CreateInput(string baseState)
    {
        var baseType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
            0.0,
            0.0,
            false,
            Enum.Parse(interactionType, "None"),
            28.0,
            120.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建工作中断 MotionInput");
    }

    private static double ReadPoseDouble(object value, string poseName, string propertyName)
    {
        var pose = ReadProperty(value, poseName)
            ?? throw new InvalidOperationException($"{poseName} 为空");
        return Convert.ToDouble(
            ReadProperty(pose, propertyName)
                ?? throw new InvalidOperationException($"{poseName}.{propertyName} 为空"),
            System.Globalization.CultureInfo.InvariantCulture);
    }

    private static double ReadDouble(object value, string propertyName) =>
        Convert.ToDouble(
            ReadProperty(value, propertyName)
                ?? throw new InvalidOperationException($"{propertyName} 为空"),
            System.Globalization.CultureInfo.InvariantCulture);

    private static object? ReadProperty(object value, string name) =>
        RequireProperty(value.GetType(), name).GetValue(value);

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
