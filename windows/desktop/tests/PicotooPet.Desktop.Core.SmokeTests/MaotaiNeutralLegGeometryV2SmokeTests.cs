using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结茅台静止站姿的腿部可读性：左右腿必须分居身体中线两侧，静止时接近自然直腿。
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

        // Canonical art is front-facing: left/right asset pairs must straddle the body center.
        // Grouping both front legs on +X and both hind legs on -X makes the rear pair read like detached side arms.
        VerifyLeg(pose, "FrontLeftUpper",  "FrontLeftLower",  "FrontLeftPaw",  expectedSideSign: -1);
        VerifyLeg(pose, "FrontRightUpper", "FrontRightLower", "FrontRightPaw", expectedSideSign: 1);
        VerifyLeg(pose, "HindLeftUpper",   "HindLeftLower",   "HindLeftPaw",   expectedSideSign: -1);
        VerifyLeg(pose, "HindRightUpper",  "HindRightLower",  "HindRightPaw",  expectedSideSign: 1);
    }

    private static void VerifyLeg(
        object pose,
        string upperName,
        string lowerName,
        string pawName,
        int expectedSideSign)
    {
        var upperX     = ReadPoseDouble(pose, upperName, "X");
        var upperY     = ReadPoseDouble(pose, upperName, "Y");
        var jointX     = ReadPoseDouble(pose, lowerName, "X");
        var jointY     = ReadPoseDouble(pose, lowerName, "Y");
        var pawX       = ReadPoseDouble(pose, pawName, "X");
        var pawY       = ReadPoseDouble(pose, pawName, "Y");
        var upperAngle = ReadPoseDouble(pose, upperName, "RotationDeg");
        var lowerAngle = ReadPoseDouble(pose, lowerName, "RotationDeg");

        Assert(expectedSideSign is -1 or 1,
            $"{upperName} 的 expectedSideSign 非法");
        Assert((upperX * expectedSideSign) >= 8.0,
            $"{upperName} 根部没有位于正确的左右半身；x={upperX:F2}");
        Assert((jointX * expectedSideSign) > 0.0,
            $"{upperName} 的膝关节穿过身体中线，静止时会形成交叉腿");
        Assert((pawX * expectedSideSign) > 0.0,
            $"{upperName} 的脚掌穿过身体中线，静止时会形成交叉站姿");

        var segmentDx            = pawX - upperX;
        var segmentDy            = pawY - upperY;
        var segmentLengthSquared = (segmentDx * segmentDx) + (segmentDy * segmentDy);
        Assert(segmentLengthSquared > 0.000001,
            $"{upperName} 静止肩脚距离无效");

        var jointProgress = (((jointX - upperX) * segmentDx) + ((jointY - upperY) * segmentDy)) /
            segmentLengthSquared;
        var projectedX = upperX + (segmentDx * jointProgress);
        var projectedY = upperY + (segmentDy * jointProgress);
        var lineDistance = Math.Sqrt(
            ((jointX - projectedX) * (jointX - projectedX)) +
            ((jointY - projectedY) * (jointY - projectedY)));

        Assert(jointProgress >= 0.38 && jointProgress <= 0.62,
            $"{upperName} 静止膝关节不在肩脚中段，腿会显得比例异常");
        Assert(lineDistance <= 1.5,
            $"{upperName} 静止膝关节偏离肩脚连线过大，仍会形成机械 Z 字腿");
        Assert(Math.Abs(NormalizeAngle(lowerAngle - upperAngle)) <= 8.0,
            $"{upperName} 静止上下腿夹角过大，不像自然站立");
    }

    private static double NormalizeAngle(double angle)
    {
        angle %= 360.0;
        if (angle > 180.0)
        {
            angle -= 360.0;
        }
        else if (angle < -180.0)
        {
            angle += 360.0;
        }

        return angle;
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
