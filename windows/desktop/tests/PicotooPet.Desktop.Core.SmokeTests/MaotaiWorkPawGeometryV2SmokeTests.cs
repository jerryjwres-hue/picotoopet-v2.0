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
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 61, 72.0)
            ?? throw new InvalidOperationException("无法创建茅台办公姿态 Motion Engine");

        var sawTyping = false;
        for (var frame = 0; frame < 720; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateWorkingInput()])
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
            28.0,
            120.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建茅台办公姿态 MotionInput");
    }

    private static double ReadPoseDouble(object value, string poseName, string propertyName)
    {
        var pose = ReadProperty(value, poseName)
            ?? throw new InvalidOperationException($"{poseName} 为空");
        return (double)(ReadProperty(pose, propertyName)
            ?? throw new InvalidOperationException($"{poseName}.{propertyName} 为空"));
    }

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
