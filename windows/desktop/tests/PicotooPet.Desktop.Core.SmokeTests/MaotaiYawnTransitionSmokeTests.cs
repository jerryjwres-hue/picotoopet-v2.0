using System.Reflection;
using System.Threading;
using System.Windows.Controls;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结疲劳 -> 哈欠 -> 工作的连续 envelope，避免嘴/身体在状态边界瞬切。</summary>
internal static class MaotaiYawnTransitionSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;
    private static readonly Type PanelType = typeof(AssistantPetPanel);

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
        object? previousPose    = null;
        object? yawnExitFrom    = null;
        object? yawnExitTo      = null;

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
                yawnExitFrom ??= previousPose;
                yawnExitTo   ??= pose;
            }

            if (previousState == "WorkAnnoyed" && state == "Recover")
            {
                annoyedToRecoverRot = Math.Abs(bodyRot - previousBodyRot);
            }

            previousState      = state;
            previousBodyScaleY = bodyScaleY;
            previousBodyRot    = bodyRot;
            previousPose       = pose;
        }

        Assert(sawYawn, "长时间 Working 必须实际进入 Yawn");
        Assert(firstOpenAmount <= 0.20, "Yawn 起势必须先小开口，禁止第一帧直接张满");
        Assert(maximumOpenAmount >= 0.90, "Yawn 中段必须达到明显张嘴峰值");
        Assert(lastOpenAmount <= 0.25, "Yawn 结束前必须基本收口，禁止切回 Typing 时硬关嘴");
        Assert(double.IsFinite(yawnToTypingJump) && yawnToTypingJump <= 0.025,
            "Yawn -> WorkTyping 身体缩放边界存在可见 snap");
        Assert(double.IsFinite(annoyedToRecoverRot) && annoyedToRecoverRot <= 0.75,
            "WorkAnnoyed -> Recover 身体张力边界存在可见 snap");
        Assert(yawnExitFrom is not null && yawnExitTo is not null,
            "Yawn 表情出口测试未观察到真实 Yawn -> WorkTyping 相邻帧");
        VerifyYawnExitFaceContinuity(yawnExitFrom!, yawnExitTo!);
    }

    /// <summary>Yawn 最后一帧已经基本收口到 Open/Smile；切回 WorkTyping 时不能把离散 Yawn 枚举重新闪回屏幕。</summary>
    private static void VerifyYawnExitFaceContinuity(object fromPose, object toPose)
    {
        var fromProgress = ReadDouble(fromPose, "YawnProgress");
        var transition   = ReadDouble(toPose, "MotionTransitionBlend");
        Assert(fromProgress >= 0.90,
            $"Yawn -> WorkTyping 测试必须从真实收口尾段取样；progress={fromProgress:F3}");
        Assert(transition >= 0.0 && transition < 0.10,
            $"WorkTyping 首帧必须仍处于 graph transition 起点；transition={transition:F3}");

        RunOnSta(() =>
        {
            var panel = new AssistantPetPanel();
            var buildVisuals = PanelType.GetMethod(
                "BuildMaotaiRasterVisuals",
                BindingFlags.Instance | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("AssistantPetPanel 缺少 BuildMaotaiRasterVisuals");
            var visuals = buildVisuals.Invoke(panel, null)
                ?? throw new InvalidOperationException("BuildMaotaiRasterVisuals 没有返回可见层集合");
            var rendererType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer");
            var renderer = Activator.CreateInstance(rendererType, visuals)
                ?? throw new InvalidOperationException("无法创建 Yawn 出口 MaotaiRasterRenderer");
            var apply = rendererType.GetMethod(
                "Apply",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("MaotaiRasterRenderer 缺少 Apply");

            var eyeOpen    = GetField<Image>(panel, "MaotaiV2EyeLeftOpen");
            var eyeHalf    = GetField<Image>(panel, "MaotaiV2EyeLeftHalf");
            var eyeClosed  = GetField<Image>(panel, "MaotaiV2EyeLeftClosed");
            var mouthSmile = GetField<Image>(panel, "MaotaiV2MouthSmile");
            var mouthTired = GetField<Image>(panel, "MaotaiV2MouthTired");
            var mouthYawn  = GetField<Image>(panel, "MaotaiV2MouthYawn");

            apply.Invoke(renderer, [fromPose]);
            var previousEyeOpen    = eyeOpen.Opacity;
            var previousEyeHalf    = eyeHalf.Opacity;
            var previousEyeClosed  = eyeClosed.Opacity;
            var previousMouthSmile = mouthSmile.Opacity;
            var previousMouthTired = mouthTired.Opacity;
            var previousMouthYawn  = mouthYawn.Opacity;

            apply.Invoke(renderer, [toPose]);
            var eyeOpenDelta    = Math.Abs(eyeOpen.Opacity - previousEyeOpen);
            var eyeHalfDelta    = Math.Abs(eyeHalf.Opacity - previousEyeHalf);
            var eyeClosedDelta  = Math.Abs(eyeClosed.Opacity - previousEyeClosed);
            var mouthSmileDelta = Math.Abs(mouthSmile.Opacity - previousMouthSmile);
            var mouthTiredDelta = Math.Abs(mouthTired.Opacity - previousMouthTired);
            var mouthYawnDelta  = Math.Abs(mouthYawn.Opacity - previousMouthYawn);

            Assert(eyeOpenDelta <= 0.20 && eyeHalfDelta <= 0.20 && eyeClosedDelta <= 0.20,
                $"Yawn -> WorkTyping 眼睛图层出口不能闪切；open={eyeOpenDelta:F3}, half={eyeHalfDelta:F3}, closed={eyeClosedDelta:F3}, progress={fromProgress:F3}, transition={transition:F3}");
            Assert(mouthSmileDelta <= 0.20 && mouthTiredDelta <= 0.20 && mouthYawnDelta <= 0.20,
                $"Yawn -> WorkTyping 嘴型图层出口不能闪切；smile={mouthSmileDelta:F3}, tired={mouthTiredDelta:F3}, yawn={mouthYawnDelta:F3}, progress={fromProgress:F3}, transition={transition:F3}");
        });
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

    private static void RunOnSta(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (failure is not null)
        {
            throw new InvalidOperationException("Maotai Yawn 出口 Renderer 连续性 smoke failed.", failure);
        }
    }

    private static T GetField<T>(object target, string fieldName) where T : class =>
        PanelType.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target) as T
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少字段 {fieldName} 或类型不是 {typeof(T).Name}");

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
