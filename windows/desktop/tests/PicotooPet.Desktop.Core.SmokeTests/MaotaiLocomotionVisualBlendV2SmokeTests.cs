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
        VerifyWorkApproachToSettleVisualContinuity();
        VerifyLegPolicyBlendsFromStableSilhouette();
        VerifyRendererConsumesTransitionEnvelopes();
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

    /// <summary>真实 Working 到达电脑时仍处于物理减速，WorkSettle 首帧不能把可见腿部直接清零。</summary>
    private static void VerifyWorkApproachToSettleVisualContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var poseType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiPoseFrame");
        var stateType  = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var policyType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLegVisualPolicy");
        var update     = RequireMethod(engineType, "Update");
        var motion     = RequireProperty(poseType, "MotionState");
        var previousMotion = RequireProperty(poseType, "PreviousMotionState");
        var locomotionBlend = RequireProperty(poseType, "LocomotionBlend");
        var transitionBlend = RequireProperty(poseType, "MotionTransitionBlend");
        var resolve = policyType.GetMethod(
            "ResolveForTransition",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("MaotaiLegVisualPolicy 缺少 ResolveForTransition");
        var engine = Activator.CreateInstance(engineType, 83, 28.0)
            ?? throw new InvalidOperationException("无法创建工作落位视觉连续性 Motion Engine");

        object? previousFrontStyle = null;
        object? previousRearStyle  = null;
        var previousState = string.Empty;
        var previousBlend = 0.0;
        var sawBoundary   = false;

        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateWorkingInput()])
                ?? throw new InvalidOperationException("工作落位视觉连续性没有输出 PoseFrame");
            var stateName = motion.GetValue(pose)?.ToString() ?? string.Empty;
            var previousStateName = previousMotion.GetValue(pose)?.ToString() ?? string.Empty;
            var locomotionValue = (double)(locomotionBlend.GetValue(pose)
                ?? throw new InvalidOperationException("WorkSettle LocomotionBlend 为空"));
            var transitionValue = (double)(transitionBlend.GetValue(pose)
                ?? throw new InvalidOperationException("WorkSettle MotionTransitionBlend 为空"));
            var state = Enum.Parse(stateType, stateName);
            var previousGraphState = Enum.Parse(stateType, previousStateName);
            var frontStyle = resolve.Invoke(
                null,
                [state, previousGraphState, true, locomotionValue, transitionValue])
                ?? throw new InvalidOperationException($"{stateName} 前腿视觉策略为空");
            var rearStyle = resolve.Invoke(
                null,
                [state, previousGraphState, false, locomotionValue, transitionValue])
                ?? throw new InvalidOperationException($"{stateName} 后腿视觉策略为空");

            if (previousState == "WorkApproach" && stateName == "WorkSettle")
            {
                Assert(previousFrontStyle is not null && previousRearStyle is not null,
                    "WorkApproach -> WorkSettle 边界缺少上一帧视觉策略");
                Assert(previousStateName == "WorkApproach",
                    $"WorkSettle PoseFrame 必须保留真实上一图节点；actual={previousStateName}");
                Assert(previousBlend >= 0.20 && locomotionValue >= 0.20,
                    $"测试必须覆盖仍在物理减速的工作落位；prevBlend={previousBlend:F3}, settleBlend={locomotionValue:F3}");
                Assert(transitionValue > 0.0 && transitionValue < 0.20,
                    $"WorkSettle 首个可见帧必须暴露早期 graph transition envelope；actual={transitionValue:F3}");

                var frontUpperDelta = Math.Abs(
                    ReadDouble(frontStyle, "UpperOpacity") -
                    ReadDouble(previousFrontStyle!, "UpperOpacity"));
                var rearUpperDelta = Math.Abs(
                    ReadDouble(rearStyle, "UpperOpacity") -
                    ReadDouble(previousRearStyle!, "UpperOpacity"));
                var rearPawDelta = Math.Abs(
                    ReadDouble(rearStyle, "PawOpacity") -
                    ReadDouble(previousRearStyle!, "PawOpacity"));
                var frontPawScaleDelta = Math.Abs(
                    ReadDouble(frontStyle, "PawScaleX") -
                    ReadDouble(previousFrontStyle!, "PawScaleX"));

                Assert(frontUpperDelta <= 0.20,
                    $"WorkApproach -> WorkSettle 前腿 Upper 不能单帧消失；delta={frontUpperDelta:F3}, prevBlend={previousBlend:F3}, settleBlend={locomotionValue:F3}");
                Assert(rearUpperDelta <= 0.20,
                    $"WorkApproach -> WorkSettle 后腿 Upper 不能单帧消失；delta={rearUpperDelta:F3}");
                Assert(rearPawDelta <= 0.20,
                    $"WorkApproach -> WorkSettle 后脚掌层级不能单帧闪亮/消失；delta={rearPawDelta:F3}");
                Assert(frontPawScaleDelta <= 0.04,
                    $"WorkApproach -> WorkSettle 前爪 footprint 不能突然变宽；delta={frontPawScaleDelta:F3}");
                sawBoundary = true;
                break;
            }

            previousFrontStyle = frontStyle;
            previousRearStyle  = rearStyle;
            previousState      = stateName;
            previousBlend      = locomotionValue;
        }

        Assert(sawBoundary,
            "工作落位视觉连续性测试未在 360 帧内观察到 WorkApproach -> WorkSettle 边界");
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

    private static void VerifyRendererConsumesTransitionEnvelopes()
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
            "Renderer 必须继续消费 PoseFrame.LocomotionBlend，真实速度仍是 locomotion 几何权重来源");
        Assert(source.Contains("frame.PreviousMotionState", StringComparison.Ordinal),
            "Renderer 必须消费上一 AnimationGraph 节点，不能猜测 WorkSettle 的来源");
        Assert(source.Contains("frame.MotionTransitionBlend", StringComparison.Ordinal),
            "Renderer 必须消费连续 graph transition envelope，不能按离散状态清空腿部图层");
        Assert(source.Contains("ResolveForTransition", StringComparison.Ordinal),
            "Renderer 必须使用跨状态连续腿部视觉策略");
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

    private static object CreateWorkingInput()
    {
        var baseStateType   = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseStateType, "Working"),
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
            ?? throw new InvalidOperationException("无法创建 Working locomotion visual MotionInput");
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
