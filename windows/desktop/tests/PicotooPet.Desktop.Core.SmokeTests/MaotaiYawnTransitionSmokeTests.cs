using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结疲劳 -> 哈欠 -> 工作的连续 envelope，避免嘴/身体在状态边界瞬切。</summary>
internal static class MaotaiYawnTransitionSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = engineType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, 101, 108.0)
            ?? throw new InvalidOperationException("无法创建 Yawn Motion Engine");

        var sawYawn             = false;
        var firstOpenAmount     = double.NaN;
        var lastOpenAmount      = double.NaN;
        var maximumOpenAmount   = 0.0;
        var previousState       = string.Empty;
        var previousBodyScaleY  = double.NaN;
        var yawnToTypingJump    = double.NaN;
        var annoyedToRecoverRot = double.NaN;
        var previousBodyRot     = double.NaN;

        for (var frame = 0; frame < 2100; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateWorkingInput()])
                ?? throw new InvalidOperationException("Yawn 测试没有输出 Pose");
            var state      = ReadString(pose, "MotionState");
            var body       = RequireProperty(pose.GetType(), "Body").GetValue(pose)
                ?? throw new InvalidOperationException("Yawn Pose 缺少 Body");
            var bodyScaleY = ReadDouble(body, "ScaleY");
            var bodyRot    = ReadDouble(body, "RotationDeg");

            if (state == "Yawn")
            {
                sawYawn = true;
                var progress = ReadDouble(pose, "YawnProgress");
                var opening  = ReadDouble(pose, "MouthOpenAmount");
                Assert(progress >= 0.0 && progress <= 1.0, "YawnProgress 必须保持 0..1");
                Assert(opening >= 0.0 && opening <= 1.0, "MouthOpenAmount 必须保持 0..1");

                if (double.IsNaN(firstOpenAmount))
                {
                    firstOpenAmount = opening;
                }

                lastOpenAmount    = opening;
                maximumOpenAmount = Math.Max(maximumOpenAmount, opening);
            }

            if (previousState == "Yawn" && state == "WorkTyping")
            {
                yawnToTypingJump = Math.Abs(bodyScaleY - previousBodyScaleY);
            }

            if (previousState == "WorkAnnoyed" && state == "Recover")
            {
                annoyedToRecoverRot = Math.Abs(bodyRot - previousBodyRot);
            }

            previousState      = state;
            previousBodyScaleY = bodyScaleY;
            previousBodyRot    = bodyRot;
        }

        Assert(sawYawn, "长时间 Working 必须实际进入 Yawn");
        Assert(firstOpenAmount <= 0.20, "Yawn 起势必须先小开口，禁止第一帧直接张满");
        Assert(maximumOpenAmount >= 0.90, "Yawn 中段必须达到明显张嘴峰值");
        Assert(lastOpenAmount <= 0.25, "Yawn 结束前必须基本收口，禁止切回 Typing 时硬关嘴");
        Assert(double.IsFinite(yawnToTypingJump) && yawnToTypingJump <= 0.025,
            "Yawn -> WorkTyping 身体缩放边界存在可见 snap");
        Assert(double.IsFinite(annoyedToRecoverRot) && annoyedToRecoverRot <= 0.75,
            "WorkAnnoyed -> Recover 身体张力边界存在可见 snap");
    }

    private static object CreateWorkingInput()
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, "Working"),
            0.0,
            0.0,
            false,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 Working MaotaiMotionInput");
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
