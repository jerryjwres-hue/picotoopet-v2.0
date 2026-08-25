using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结茅台办公姿态的左右前爪几何：两只前爪必须分别落在键盘中线两侧，禁止跨胸交叉敲键盘。
/// </summary>
internal static class MaotaiWorkPawGeometryV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyTypingGeometry();
        VerifyWorkExitContinuity();
        VerifyInterruptedTiredExitContinuity();
    }

    private static void VerifyTypingGeometry()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 61, 72.0)
            ?? throw new InvalidOperationException("无法创建茅台办公姿态 Motion Engine");

        var sawTyping = false;
        for (var frame = 0; frame < 720; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("办公姿态没有输出 PoseFrame");
            if (!string.Equals(ReadProperty(pose, "MotionState")?.ToString(), "WorkTyping", StringComparison.Ordinal))
            {
                continue;
            }

            sawTyping = true;
            var facingSign = (int)(ReadProperty(pose, "FacingSign")
                ?? throw new InvalidOperationException("FacingSign 为空"));
            Assert(facingSign == 1,
                $"测试夹具必须从左侧进入工作锚点，确保 canonical 正面坐标可判定；facingSign={facingSign}");

            var leftShoulderX = ReadPoseDouble(pose, "FrontLeftUpper", "X");
            var rightShoulderX = ReadPoseDouble(pose, "FrontRightUpper", "X");
            var leftPawX = ReadPoseDouble(pose, "FrontLeftPaw", "X");
            var rightPawX = ReadPoseDouble(pose, "FrontRightPaw", "X");

            Assert(leftShoulderX <= -8.0 && rightShoulderX >= 8.0,
                $"办公前腿根必须分居身体中线两侧；left={leftShoulderX:F2}, right={rightShoulderX:F2}");
            Assert(leftPawX <= -3.0,
                $"左前爪跨过身体中线去敲右侧键盘，视觉上会形成横穿胸口的撕裂手臂；leftPawX={leftPawX:F2}");
            Assert(rightPawX >= 3.0,
                $"右前爪越过身体中线，办公姿态左右手语义错误；rightPawX={rightPawX:F2}");
            Assert(leftPawX < rightPawX,
                $"办公两爪左右顺序颠倒；leftPawX={leftPawX:F2}, rightPawX={rightPawX:F2}");
            break;
        }

        Assert(sawTyping, "Working 在 12 秒内没有进入 WorkTyping，无法验证键盘前爪几何");
    }

    /// <summary>退出 Working 的第一帧不能把身体和双前爪从键盘姿态直接弹回中性站姿。</summary>
    private static void VerifyWorkExitContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 67, 108.0)
            ?? throw new InvalidOperationException("无法创建工作退出连续性 Motion Engine");

        object? typingPose = null;
        for (var frame = 0; frame < 240; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("工作退出预热没有输出 PoseFrame");
            if (string.Equals(ReadProperty(pose, "MotionState")?.ToString(), "WorkTyping", StringComparison.Ordinal) &&
                ReadDouble(pose, "MotionTransitionBlend") >= 0.999)
            {
                typingPose = pose;
                break;
            }
        }

        Assert(typingPose is not null, "工作退出连续性测试未能进入稳定 WorkTyping");

        var idlePose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
            ?? throw new InvalidOperationException("工作退出首帧没有输出 PoseFrame");
        var state = ReadProperty(idlePose, "MotionState")?.ToString();
        Assert(string.Equals(state, "Idle", StringComparison.Ordinal),
            $"稳定 WorkTyping 退出到 Resting 后首跳应为 Idle；actual={state}");

        var bodyYDelta = Math.Abs(
            ReadPoseDouble(idlePose, "Body", "Y") - ReadPoseDouble(typingPose!, "Body", "Y"));
        var bodyScaleYDelta = Math.Abs(
            ReadPoseDouble(idlePose, "Body", "ScaleY") - ReadPoseDouble(typingPose!, "Body", "ScaleY"));
        var leftPawDelta = PoseDistance(typingPose!, idlePose, "FrontLeftPaw");
        var rightPawDelta = PoseDistance(typingPose!, idlePose, "FrontRightPaw");

        Assert(bodyYDelta < 0.75,
            $"WorkTyping→Idle 身体高度不能首帧弹回中性姿态；delta={bodyYDelta:F3}");
        Assert(bodyScaleYDelta < 0.012,
            $"WorkTyping→Idle 身体纵向缩放不能首帧硬切；delta={bodyScaleYDelta:F4}");
        Assert(leftPawDelta < 1.60,
            $"WorkTyping→Idle 左前爪不能从键盘瞬移回站姿；delta={leftPawDelta:F3}");
        Assert(rightPawDelta < 1.60,
            $"WorkTyping→Idle 右前爪不能从键盘瞬移回站姿；delta={rightPawDelta:F3}");
    }

    /// <summary>真实 Working 在疲劳节点结束时，Recover 必须从当前疲劳姿态继续，而不是套用烦躁恢复起点。</summary>
    private static void VerifyInterruptedTiredExitContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 71, 108.0)
            ?? throw new InvalidOperationException("无法创建疲劳打断连续性 Motion Engine");

        object? tiredPose = null;
        for (var frame = 0; frame < 720; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("疲劳打断预热没有输出 PoseFrame");
            if (string.Equals(ReadProperty(pose, "MotionState")?.ToString(), "WorkTired", StringComparison.Ordinal) &&
                ReadDouble(pose, "MotionTransitionBlend") >= 0.999)
            {
                tiredPose = pose;
                break;
            }
        }

        Assert(tiredPose is not null, "疲劳打断连续性测试未能进入稳定 WorkTired");

        var recoverPose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting")])
            ?? throw new InvalidOperationException("疲劳打断退出首帧没有输出 PoseFrame");
        var state = ReadProperty(recoverPose, "MotionState")?.ToString();
        Assert(string.Equals(state, "Recover", StringComparison.Ordinal),
            $"WorkTired 被 Resting 打断后的安全回退首跳应为 Recover；actual={state}");

        var bodyYDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "Y") - ReadPoseDouble(tiredPose!, "Body", "Y"));
        var bodyScaleXDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "ScaleX") - ReadPoseDouble(tiredPose!, "Body", "ScaleX"));
        var bodyScaleYDelta = Math.Abs(
            ReadPoseDouble(recoverPose, "Body", "ScaleY") - ReadPoseDouble(tiredPose!, "Body", "ScaleY"));

        Assert(bodyYDelta < 0.75,
            $"WorkTired→Recover 身体高度不能切到烦躁恢复起点；delta={bodyYDelta:F3}");
        Assert(bodyScaleXDelta < 0.012,
            $"WorkTired→Recover 身体横向缩放不能节点硬切；delta={bodyScaleXDelta:F4}");
        Assert(bodyScaleYDelta < 0.012,
            $"WorkTired→Recover 身体纵向缩放不能节点硬切；delta={bodyScaleYDelta:F4}");
    }

    private static object CreateInput(string baseState)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

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
            ?? throw new InvalidOperationException("无法创建茅台办公姿态 MotionInput");
    }

    private static double PoseDistance(object previous, object current, string poseName)
    {
        var dx = ReadPoseDouble(current, poseName, "X") - ReadPoseDouble(previous, poseName, "X");
        var dy = ReadPoseDouble(current, poseName, "Y") - ReadPoseDouble(previous, poseName, "Y");
        return Math.Sqrt((dx * dx) + (dy * dy));
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
