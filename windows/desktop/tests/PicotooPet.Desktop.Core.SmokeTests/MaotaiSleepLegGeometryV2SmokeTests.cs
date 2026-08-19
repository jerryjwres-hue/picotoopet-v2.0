using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>
/// 冻结真正 Sleep 姿态的四肢几何：身体下沉后脚掌必须跟随身体收拢，不能继续被地面锁定成折叠纸片。
/// </summary>
internal static class MaotaiSleepLegGeometryV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 173, 72.0)
            ?? throw new InvalidOperationException("无法创建茅台 Sleep 四肢几何 Motion Engine");
        var input      = CreateOfflineInput();

        object? pose = null;
        for (var frame = 0; frame < 360; frame++)
        {
            pose = update.Invoke(engine, [1.0 / 60.0, input]);
        }

        if (pose is null)
        {
            throw new InvalidOperationException("Sleep 四肢几何测试没有输出 PoseFrame");
        }

        Assert(
            string.Equals(ReadProperty(pose, "MotionState").ToString(), "Sleep", StringComparison.Ordinal),
            $"离线 6 秒后仍未稳定进入 Sleep；actual={ReadProperty(pose, "MotionState")}");

        VerifyTuckedLeg(pose, "FrontLeftUpper",  "FrontLeftLower",  "FrontLeftPaw",  "FrontLeftPawWorldY");
        VerifyTuckedLeg(pose, "FrontRightUpper", "FrontRightLower", "FrontRightPaw", "FrontRightPawWorldY");
        VerifyTuckedLeg(pose, "HindLeftUpper",   "HindLeftLower",   "HindLeftPaw",   "HindLeftPawWorldY");
        VerifyTuckedLeg(pose, "HindRightUpper",  "HindRightLower",  "HindRightPaw",  "HindRightPawWorldY");
    }

    private static void VerifyTuckedLeg(
        object pose,
        string upperName,
        string lowerName,
        string pawName,
        string pawWorldYName)
    {
        var upperAngle = ReadPoseDouble(pose, upperName, "RotationDeg");
        var lowerAngle = ReadPoseDouble(pose, lowerName, "RotationDeg");
        var pawX       = ReadPoseDouble(pose, pawName, "X");
        var pawY       = ReadPoseDouble(pose, pawName, "Y");
        var pawWorldY  = ReadDouble(pose, pawWorldYName);

        Assert(double.IsFinite(upperAngle) && double.IsFinite(lowerAngle) &&
               double.IsFinite(pawX) && double.IsFinite(pawY) && double.IsFinite(pawWorldY),
            $"{upperName} Sleep 姿态出现非有限数值");

        // Ground release    : Sleep 身体已经下沉，脚掌若仍固定 worldY=0 会把 19+18px 的 IK 腿压成锐角纸片。
        Assert(pawWorldY <= -0.5,
            $"{pawName} Sleep 时仍被锁在地面；pawWorldY={pawWorldY:F2}");

        // Fold limit        : 收拢可以弯腿，但上下段不能形成超过 90° 的反折，避免素材接缝横向炸开。
        var jointFold = Math.Abs(NormalizeAngle(lowerAngle - upperAngle));
        Assert(jointFold <= 90.0,
            $"{upperName} Sleep 上下腿折角过大；fold={jointFold:F1}°");
    }

    private static object CreateOfflineInput()
    {
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var baseStateType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");

        return Activator.CreateInstance(
            inputType,
            [
                Enum.Parse(baseStateType, "Offline"),
                0.0,
                0.0,
                false,
                Enum.Parse(interactionType, "None"),
                18.0,
                150.0,
                72.0,
                false,
                false,
                70.0,
            ]) ?? throw new InvalidOperationException("无法创建 Sleep 四肢几何 MotionInput");
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

    private static double ReadPoseDouble(object value, string poseName, string propertyName)
    {
        var pose = ReadProperty(value, poseName);
        return Convert.ToDouble(
            ReadProperty(pose, propertyName),
            System.Globalization.CultureInfo.InvariantCulture);
    }

    private static double ReadDouble(object target, string name) =>
        Convert.ToDouble(
            ReadProperty(target, name),
            System.Globalization.CultureInfo.InvariantCulture);

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static Type RequireType(string name) =>
        DesktopAssembly.GetType(name, throwOnError: true)!;

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
