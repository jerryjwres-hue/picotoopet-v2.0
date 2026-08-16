using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结茅台静止站姿的腿部可读性：独立上下腿可以轻微折膝，但不能穿过身体中线形成 X 型交叉。
/// 骨长代表两个关节 Pivot 之间的有效距离，不等于整张带 overlap 的 PNG 高度。
/// </summary>
internal static class MaotaiNeutralLegGeometryV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 43, 72.0)
            ?? throw new InvalidOperationException("无法创建茅台中性站姿 Motion Engine");

        object? pose = null;
        for (var frame = 0; frame < 120; frame++)
        {
            pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput()]);
        }

        if (pose is null)
        {
            throw new InvalidOperationException("中性站姿没有输出 PoseFrame");
        }

        VerifyLeg(pose, "FrontLeftUpper", "FrontLeftLower", front: true);
        VerifyLeg(pose, "FrontRightUpper", "FrontRightLower", front: true);
        VerifyLeg(pose, "HindLeftUpper", "HindLeftLower", front: false);
        VerifyLeg(pose, "HindRightUpper", "HindRightLower", front: false);
    }

    private static void VerifyLeg(object pose, string upperName, string lowerName, bool front)
    {
        var upperX = ReadPoseDouble(pose, upperName, "X");
        var jointX = ReadPoseDouble(pose, lowerName, "X");

        if (front)
        {
            Assert(upperX > 0.0 && jointX > 0.0,
                $"{upperName} 的膝关节穿过身体中线，静止时会形成 X 型前腿");
        }
        else
        {
            Assert(upperX < 0.0 && jointX < 0.0,
                $"{upperName} 的膝关节穿过身体中线，静止时会形成 X 型后腿");
        }

        Assert(Math.Abs(jointX - upperX) <= 12.0,
            $"{upperName} 静止折膝横向位移过大，会显得像手臂张开而不是自然站立");
    }

    private static object CreateRestingInput()
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, "Resting"),
            0.0,
            0.0,
            false,
            Enum.Parse(interactionType, "None"),
            28.0,
            120.0,
            72.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建茅台中性站姿 MotionInput");
    }

    private static double ReadPoseDouble(object value, string poseName, string propertyName)
    {
        var pose = RequireProperty(value.GetType(), poseName).GetValue(value)
            ?? throw new InvalidOperationException($"{poseName} 为空");
        return (double)(RequireProperty(pose.GetType(), propertyName).GetValue(pose)
            ?? throw new InvalidOperationException($"{poseName}.{propertyName} 为空"));
    }

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
