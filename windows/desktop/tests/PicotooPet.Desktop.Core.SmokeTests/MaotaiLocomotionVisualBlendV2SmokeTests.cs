using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 locomotion 视觉权重的连续性，防止状态切换时腿部几何/显隐瞬间闪跳。</summary>
internal static class MaotaiLocomotionVisualBlendV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyMotionEnvelopeIsContinuous();
        VerifyLegPolicyBlendsFromStableSilhouette();
        VerifyRendererConsumesLocomotionBlend();
    }

    private static void VerifyMotionEnvelopeIsContinuous()
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

    private static void VerifyLegPolicyBlendsFromStableSilhouette()
    {
        var policyType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLegVisualPolicy");
        var stateType  = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var resolve    = policyType.GetMethod(
            "ResolveForBlend",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiLegVisualPolicy 缺少 ResolveForBlend");

        foreach (var stateName in new[] { "Walk", "Run", "WorkApproach" })
        {
            var state = Enum.Parse(stateType, stateName);
            var start = resolve.Invoke(null, [state, true, 0.0])
                ?? throw new InvalidOperationException($"{stateName} 起步视觉策略为空");
            var mid = resolve.Invoke(null, [state, true, 0.5])
                ?? throw new InvalidOperationException($"{stateName} 中段视觉策略为空");
            var full = resolve.Invoke(null, [state, true, 1.0])
                ?? throw new InvalidOperationException($"{stateName} 满速视觉策略为空");

            Assert(ReadDouble(start, "LowerOpacity") <= 0.001,
                $"{stateName} 起步首帧 Lower 必须从稳定轮廓的透明状态开始");
            Assert(ReadDouble(start, "PawScaleX") >= 0.999,
                $"{stateName} 起步首帧 Paw footprint 不得瞬间缩窄");
            Assert(ReadDouble(mid, "LowerOpacity") > ReadDouble(start, "LowerOpacity") &&
                   ReadDouble(mid, "LowerOpacity") < ReadDouble(full, "LowerOpacity"),
                $"{stateName} Lower 毛桥必须随 locomotion blend 渐入");
            Assert(ReadDouble(mid, "PawScaleX") < ReadDouble(start, "PawScaleX") &&
                   ReadDouble(mid, "PawScaleX") > ReadDouble(full, "PawScaleX"),
                $"{stateName} Paw footprint 必须连续收敛，禁止状态瞬切");
        }

        var runState  = Enum.Parse(stateType, "Run");
        var rearStart = resolve.Invoke(null, [runState, false, 0.0])
            ?? throw new InvalidOperationException("Run 后腿起步视觉策略为空");
        var rearFull = resolve.Invoke(null, [runState, false, 1.0])
            ?? throw new InvalidOperationException("Run 后腿满速视觉策略为空");

        Assert(ReadDouble(rearStart, "UpperOpacity") >= 0.999 &&
               ReadDouble(rearStart, "PawOpacity") >= 0.999,
            "Run 后腿进入运动时必须先从稳定轮廓连续过渡，不能第一帧直接变淡");
        Assert(ReadDouble(rearFull, "UpperOpacity") < 0.40 &&
               ReadDouble(rearFull, "PawOpacity") < 0.30,
            "Run 满速后腿仍需回到后景权重，避免抢到前腿前面");
    }

    private static void VerifyRendererConsumesLocomotionBlend()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Views",
            "Controls",
            "MaotaiMotion",
            "MaotaiRasterRenderer.cs");
        var source = File.ReadAllText(path);

        Assert(source.Contains("frame.LocomotionBlend", StringComparison.Ordinal),
            "Renderer 必须消费 PoseFrame.LocomotionBlend，不能继续只按 MotionState 切腿部几何");
        Assert(source.Contains("ResolveForBlend", StringComparison.Ordinal),
            "Renderer 必须使用连续腿部视觉策略，而不是只调用离散 Resolve");
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

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static string FindRepositoryRoot()
    {
        var current = new DirectoryInfo(AppContext.BaseDirectory);
        while (current is not null)
        {
            var marker = Path.Combine(current.FullName, "windows", "desktop", "global.json");
            if (File.Exists(marker))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        throw new InvalidOperationException("无法定位仓库根目录");
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
