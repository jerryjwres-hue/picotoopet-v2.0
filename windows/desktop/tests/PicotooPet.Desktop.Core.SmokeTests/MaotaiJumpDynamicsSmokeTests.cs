using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 JumpPrep -> Air -> Land 的真实全身动力学，避免退化成只改状态名或单帧位移。</summary>
internal static class MaotaiJumpDynamicsSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = engineType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, 89, 70.0)
            ?? throw new InvalidOperationException("无法创建 Jump Motion Engine");

        var sawPrep        = false;
        var sawAir         = false;
        var sawLand        = false;
        var minimumPrepY   = 1.0;
        var minimumAirY    = 0.0;
        var minimumLandY   = 1.0;
        var maximumLandX   = 1.0;

        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(
                engine,
                [1.0 / 60.0, CreateInput(wantsJump: frame == 0)])
                ?? throw new InvalidOperationException("Jump 测试没有输出 Pose");
            var state      = ReadString(pose, "MotionState");
            var body       = RequireProperty(pose.GetType(), "Body").GetValue(pose)
                ?? throw new InvalidOperationException("Jump Pose 缺少 Body");
            var bodyScaleX = ReadDouble(body, "ScaleX");
            var bodyScaleY = ReadDouble(body, "ScaleY");
            var stageY     = ReadDouble(pose, "StageYOffset");

            switch (state)
            {
                case "JumpPrep":
                    sawPrep      = true;
                    minimumPrepY = Math.Min(minimumPrepY, bodyScaleY);
                    break;

                case "JumpAir":
                    sawAir      = true;
                    minimumAirY = Math.Min(minimumAirY, stageY);
                    break;

                case "Land":
                    sawLand      = true;
                    minimumLandY = Math.Min(minimumLandY, bodyScaleY);
                    maximumLandX = Math.Max(maximumLandX, bodyScaleX);
                    break;
            }
        }

        Assert(sawPrep, "JumpAir 前必须真实经过 JumpPrep");
        Assert(sawAir, "JumpPrep 后必须进入 JumpAir");
        Assert(sawLand, "JumpAir 后必须进入 Land");
        Assert(minimumPrepY <= 0.94, "JumpPrep 必须有明显纵向 squash 蓄力");
        Assert(minimumAirY <= -8.0, "JumpAir 必须产生真实离地高度");
        Assert(minimumLandY <= 0.95, "Land 必须有纵向压缩吸收冲击");
        Assert(maximumLandX >= 1.04, "Land 必须有横向 squash/recoil 配合，而不是硬落地");
    }

    private static object CreateInput(bool wantsJump)
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
            20.0,
            140.0,
            70.0,
            wantsJump,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 Jump MaotaiMotionInput");
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
