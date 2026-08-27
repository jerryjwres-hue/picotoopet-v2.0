using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结中段哈欠被摸头即时打断时的身体与键盘前爪连续性。</summary>
internal static class MaotaiInterruptedYawnPatV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = RequireMethod(engineType, "Update");
        var engine = Activator.CreateInstance(engineType, 101, 108.0)
            ?? throw new InvalidOperationException("无法创建哈欠摸头中断 Motion Engine");

        object? yawnPose = null;
        for (var frame = 0; frame < 1200; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working")])
                ?? throw new InvalidOperationException("哈欠摸头中断预热没有输出 PoseFrame");
            var state = ReadProperty(pose, "MotionState")?.ToString();
            var transitionBlend = ReadDouble(pose, "MotionTransitionBlend");
            var yawnProgress = ReadDouble(pose, "YawnProgress");
            if (string.Equals(state, "Yawn", StringComparison.Ordinal) &&
                transitionBlend >= 0.999 &&
                yawnProgress >= 0.45 && yawnProgress <= 0.55)
            {
                yawnPose = pose;
                break;
            }
        }

        Assert(yawnPose is not null, "哈欠摸头中断测试未捕获到稳定过渡后的中段 Yawn");

        var patPose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Working", "Pat")])
            ?? throw new InvalidOperationException("哈欠摸头中断首帧没有输出 PoseFrame");
        var patState = ReadProperty(patPose, "MotionState")?.ToString();
        Assert(string.Equals(patState, "UserReaction", StringComparison.Ordinal),
            $"Pat 必须首帧打断 Yawn 并进入 UserReaction；actual={patState}");
        Assert(string.Equals(ReadProperty(patPose, "MouthState")?.ToString(), "Tongue", StringComparison.Ordinal),
            "Pat 打断 Yawn 的首帧必须立即显示 Tongue，连续性不能延迟互动反馈");

        var bodyYDelta = Math.Abs(
            ReadPoseDouble(patPose, "Body", "Y") - ReadPoseDouble(yawnPose!, "Body", "Y"));
        var bodyScaleXDelta = Math.Abs(
            ReadPoseDouble(patPose, "Body", "ScaleX") - ReadPoseDouble(yawnPose!, "Body", "ScaleX"));
        var bodyScaleYDelta = Math.Abs(
            ReadPoseDouble(patPose, "Body", "ScaleY") - ReadPoseDouble(yawnPose!, "Body", "ScaleY"));
        var leftPawDelta = PoseDistance(yawnPose!, patPose, "FrontLeftPaw");
        var rightPawDelta = PoseDistance(yawnPose!, patPose, "FrontRightPaw");

        Assert(bodyYDelta < 0.75,
            $"Pat 打断中段 Yawn 时身体高度不能瞬间归零；delta={bodyYDelta:F3}");
        Assert(bodyScaleXDelta < 0.012,
            $"Pat 打断中段 Yawn 时横向缩放不能瞬间归零；delta={bodyScaleXDelta:F4}");
        Assert(bodyScaleYDelta < 0.012,
            $"Pat 打断中段 Yawn 时纵向缩放不能瞬间归零；delta={bodyScaleYDelta:F4}");
        Assert(leftPawDelta < 1.60,
            $"Pat 打断中段 Yawn 时左前爪不能从键盘瞬移回站姿；delta={leftPawDelta:F3}");
        Assert(rightPawDelta < 1.60,
            $"Pat 打断中段 Yawn 时右前爪不能从键盘瞬移回站姿；delta={rightPawDelta:F3}");
    }

    private static object CreateInput(string baseState, string interaction = "None")
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
            Enum.Parse(interactionType, interaction),
            28.0,
            120.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建哈欠摸头中断 MotionInput");
    }

    private static double PoseDistance(object from, object to, string poseName)
    {
        var dx = ReadPoseDouble(to, poseName, "X") - ReadPoseDouble(from, poseName, "X");
        var dy = ReadPoseDouble(to, poseName, "Y") - ReadPoseDouble(from, poseName, "Y");
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
