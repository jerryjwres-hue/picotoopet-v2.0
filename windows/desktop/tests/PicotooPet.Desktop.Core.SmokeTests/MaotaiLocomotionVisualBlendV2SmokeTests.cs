using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 locomotion 视觉权重的连续性，防止状态切换时腿部几何/显隐瞬间闪跳。</summary>
internal static class MaotaiLocomotionVisualBlendV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var poseType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiPoseFrame");
        var update     = RequireMethod(engineType, "Update");
        var blend      = RequireProperty(poseType, "LocomotionBlend");
        var engine     = Activator.CreateInstance(engineType, 61, 42.0)
            ?? throw new InvalidOperationException("无法创建 locomotion blend Motion Engine");

        var previous = 0.0;
        var peak     = 0.0;
        for (var frame = 0; frame < 300; frame++)
        {
            // Acceleration       : first half asks for a real run toward the far edge.
            // Deceleration       : second half returns to the start without Run, exercising the fade-out path.
            var input = CreateInput(
                targetX: frame < 150 ? 138.0 : 42.0,
                wantsRun: frame < 150);
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("locomotion blend 没有输出 PoseFrame");
            var value = (double)(blend.GetValue(pose)
                ?? throw new InvalidOperationException("LocomotionBlend 为空"));

            Assert(double.IsFinite(value) && value >= 0.0 && value <= 1.0,
                $"LocomotionBlend 必须保持 0..1；actual={value:F4}");
            Assert(Math.Abs(value - previous) <= 0.07,
                $"LocomotionBlend 单帧跳变过大，会让腿部图层闪切；prev={previous:F4}, actual={value:F4}");

            previous = value;
            peak     = Math.Max(peak, value);
        }

        Assert(peak >= 0.80,
            "连续 locomotion blend 从未进入明确运动区间，Renderer 无法平滑进入关节步态");
    }

    private static object CreateInput(double targetX, bool wantsRun)
    {
        var baseStateType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseStateType, "Resting"),
            0.0,
            0.0,
            false,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            targetX,
            wantsRun,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 locomotion blend MotionInput");
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName)
        ?? throw new InvalidOperationException($"缺少类型 {fullName}");

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Public | BindingFlags.Instance)
        ?? throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance)
        ?? throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
