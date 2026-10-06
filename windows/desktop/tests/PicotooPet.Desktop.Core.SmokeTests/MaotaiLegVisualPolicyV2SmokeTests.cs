using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台运动腿部的混合关节显示策略，禁止再次用拉长单图或完整块状双段腿伪装自然动作。</summary>
internal static class MaotaiLegVisualPolicyV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyIdleKeepsStableContinuousSilhouette();
        VerifyLocomotionUsesSubtleFrontKneeBridge();
        VerifyLocomotionKeepsRearDepthWithoutFullBlockStack();
        VerifyFoldedStatesKeepLongSegmentsOccluded();
    }

    private static void VerifyIdleKeepsStableContinuousSilhouette()
    {
        var style = Resolve("Idle", isFront: true);

        Assert(!ReadBool(style, "UseArticulation"),
            "Idle 不应强制暴露双段腿，否则静止站姿会回到机械拼装感");
        Assert(ReadDouble(style, "UpperOpacity") >= 0.99,
            "Idle 前腿 Upper 必须保持可见");
        Assert(ReadDouble(style, "LowerOpacity") <= 0.01,
            "Idle Lower 应继续隐藏在稳定连续轮廓中");
        Assert(ReadDouble(style, "PawOpacity") >= 0.99,
            "Idle 脚掌必须保持可见");
    }

    private static void VerifyLocomotionUsesSubtleFrontKneeBridge()
    {
        foreach (var state in new[] { "Walk", "Run" })
        {
            var style = Resolve(state, isFront: true);

            // Real knee            : moving front legs follow Upper→Lower→Paw from IK.
            // Fur bridge           : Lower remains deliberately narrow/faint so it cannot become a second rectangular limb block.
            Assert(ReadBool(style, "UseArticulation"),
                $"{state} 前腿必须使用真实 Upper→Lower→Paw 关节链");
            Assert(ReadDouble(style, "UpperOpacity") >= 0.99,
                $"{state} 前腿 Upper 必须完整可见");
            Assert(ReadDouble(style, "LowerOpacity") >= 0.15 && ReadDouble(style, "LowerOpacity") <= 0.35,
                $"{state} 前腿 Lower 必须是可读但克制的毛发关节桥");
            Assert(ReadDouble(style, "LowerScaleX") <= 0.65,
                $"{state} 前腿 Lower 必须收窄，禁止恢复完整块状腿");
            Assert(ReadDouble(style, "PawOpacity") >= 0.99,
                $"{state} 前爪必须保持可见");
            Assert(ReadDouble(style, "PawScaleX") >= 0.88,
                $"{state} 前爪禁止再次压窄成细柱脚");
        }
    }

    private static void VerifyLocomotionKeepsRearDepthWithoutFullBlockStack()
    {
        foreach (var state in new[] { "Walk", "Run" })
        {
            var front = Resolve(state, isFront: true);
            var rear  = Resolve(state, isFront: false);

            // Rear silhouette      : retain motion/depth evidence, but do not expose another full articulated stack in front view.
            Assert(!ReadBool(rear, "UseArticulation"),
                $"{state} 后腿前视角应使用低权重连续毛发轮廓，而不是第二组完整块状关节");
            Assert(ReadDouble(rear, "UpperOpacity") >= 0.20,
                $"{state} 后腿 Upper 不得再次完全消失");
            Assert(ReadDouble(rear, "LowerOpacity") <= 0.01,
                $"{state} 后腿 Lower 应隐藏在连续后景毛发里");
            Assert(ReadDouble(rear, "PawOpacity") >= 0.10,
                $"{state} 后脚掌必须保留轻微接触语义");
            Assert(ReadDouble(rear, "UpperOpacity") < ReadDouble(front, "UpperOpacity"),
                $"{state} 后腿必须保持后景权重，避免抢到前腿前面");
        }
    }

    private static void VerifyFoldedStatesKeepLongSegmentsOccluded()
    {
        foreach (var state in new[] { "WorkTyping", "Sleep", "LieDown" })
        {
            var style = Resolve(state, isFront: true);

            // Folded pose          : paws may remain for typing/rest contact, long segments stay under torso fur.
            Assert(!ReadBool(style, "UseArticulation"),
                $"{state} 不应暴露运动用双段腿");
            Assert(ReadDouble(style, "UpperOpacity") <= 0.01,
                $"{state} 长 Upper 应由身体自然遮挡");
            Assert(ReadDouble(style, "LowerOpacity") <= 0.01,
                $"{state} 长 Lower 应由身体自然遮挡");
            Assert(ReadDouble(style, "PawOpacity") >= 0.99,
                $"{state} 脚掌仍需保留接触/打字语义");
        }
    }

    private static object Resolve(string stateName, bool isFront)
    {
        var policyType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLegVisualPolicy");
        var stateType  = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var resolve    = policyType.GetMethod("Resolve", BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiLegVisualPolicy 缺少 public static Resolve");
        var state      = Enum.Parse(stateType, stateName);

        return resolve.Invoke(null, [state, isFront])
            ?? throw new InvalidOperationException($"{stateName} 腿部视觉策略为空");
    }

    private static bool ReadBool(object value, string propertyName) =>
        (bool)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName)
        ?? throw new InvalidOperationException($"缺少类型 {fullName}");

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
