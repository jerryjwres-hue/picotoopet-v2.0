using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 后半程的资产、全身姿态、锁脚和长时间稳定性合同。</summary>
internal static class MaotaiNaturalMotionV2AcceptanceSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyIndependentAssetGate();
        VerifyAllFeetExposeLockTelemetry();
        VerifyNaturalWorkPosture();
        VerifyTenMinuteEquivalentSoak();
        VerifyReleaseBundlesV2Assets();
    }

    private static void VerifyIndependentAssetGate()
    {
        var manifestType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest");
        var tryGet       = manifestType.GetMethod(
            "TryGetDescriptor",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("v2 资产 manifest 缺少 TryGetDescriptor 元数据 Gate");

        string[] requiredAssets =
        [
            "torso_neutral.png", "torso_crouch.png", "torso_stretch.png", "chest_fur.png",
            "head.png", "muzzle.png", "ear_left.png", "ear_right.png",
            "front_left_upper.png", "front_left_lower.png", "front_left_paw.png",
            "front_right_upper.png", "front_right_lower.png", "front_right_paw.png",
            "hind_left_upper.png", "hind_left_lower.png", "hind_left_paw.png",
            "hind_right_upper.png", "hind_right_lower.png", "hind_right_paw.png",
            "tail_base.png", "tail_mid.png", "tail_tip.png",
            "headphone_band.png", "headphone_left.png", "headphone_right.png",
            "laptop.png", "drink.png", "shadow.png",
        ];

        foreach (var fileName in requiredAssets)
        {
            object?[] arguments = [fileName, null];
            Assert((bool)tryGet.Invoke(null, arguments)!, $"v2 资产缺少布局元数据：{fileName}");
            var descriptor = arguments[1]
                ?? throw new InvalidOperationException($"v2 资产描述为空：{fileName}");
            var width      = ReadDouble(descriptor, "Width");
            var height     = ReadDouble(descriptor, "Height");
            var pivotX     = ReadDouble(descriptor, "PivotX");
            var pivotY     = ReadDouble(descriptor, "PivotY");
            var overlap    = ReadDouble(descriptor, "JointOverlapPixels");

            Assert(width > 0.0 && height > 0.0, $"v2 资产逻辑尺寸非法：{fileName}");
            Assert(pivotX >= 0.0 && pivotX <= width && pivotY >= 0.0 && pivotY <= height,
                $"v2 资产 Pivot 越界：{fileName}");
            Assert(overlap >= 12.0, $"v2 关节隐藏重叠区不足 12px：{fileName}");
        }
    }

    private static void VerifyAllFeetExposeLockTelemetry()
    {
        var poseType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiPoseFrame");
        string[] properties =
        [
            "FrontLeftSupport", "FrontLeftPawWorldX", "FrontLeftPawWorldY",
            "FrontRightSupport", "FrontRightPawWorldX", "FrontRightPawWorldY",
            "HindLeftSupport", "HindLeftPawWorldX", "HindLeftPawWorldY",
            "HindRightSupport", "HindRightPawWorldX", "HindRightPawWorldY",
        ];

        foreach (var property in properties)
        {
            _ = RequireProperty(poseType, property);
        }
    }

    private static void VerifyNaturalWorkPosture()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 53, 108.0)
            ?? throw new InvalidOperationException("无法创建工作姿态 Motion Engine");

        var typingHeadY    = double.NaN;
        var tiredHeadY     = double.NaN;
        var yawnBodyScaleY = double.NaN;
        var annoyedTilt    = double.NaN;
        var tiredPawTravel = 0.0;
        var annoyedPawTravel = 0.0;
        var previousTiredPawY = double.NaN;
        var previousAnnoyedPawY = double.NaN;

        for (var frame = 0; frame < 1800; frame++)
        {
            var input = CreateInput("Working", 108.0, 108.0);
            var pose  = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("工作姿态没有输出 Pose");
            var state = ReadString(pose, "MotionState");

            if (state == "WorkTyping" && double.IsNaN(typingHeadY))
            {
                typingHeadY = ReadPoseDouble(pose, "Head", "Y");
            }
            else if (state == "WorkTired")
            {
                tiredHeadY = Math.Max(
                    double.IsNaN(tiredHeadY) ? double.NegativeInfinity : tiredHeadY,
                    ReadPoseDouble(pose, "Head", "Y"));
                var pawY = ReadPoseDouble(pose, "FrontLeftPaw", "Y");
                if (!double.IsNaN(previousTiredPawY))
                {
                    tiredPawTravel += Math.Abs(pawY - previousTiredPawY);
                }
                previousTiredPawY = pawY;
            }
            else if (state == "Yawn")
            {
                yawnBodyScaleY = Math.Max(
                    double.IsNaN(yawnBodyScaleY) ? double.NegativeInfinity : yawnBodyScaleY,
                    ReadPoseDouble(pose, "Body", "ScaleY"));
            }
            else if (state == "WorkAnnoyed")
            {
                annoyedTilt = Math.Max(
                    double.IsNaN(annoyedTilt) ? double.NegativeInfinity : annoyedTilt,
                    Math.Abs(ReadPoseDouble(pose, "Body", "RotationDeg")));
                var pawY = ReadPoseDouble(pose, "FrontLeftPaw", "Y");
                if (!double.IsNaN(previousAnnoyedPawY))
                {
                    annoyedPawTravel += Math.Abs(pawY - previousAnnoyedPawY);
                }
                previousAnnoyedPawY = pawY;
            }
        }

        Assert(double.IsFinite(typingHeadY) && double.IsFinite(tiredHeadY), "工作循环缺少 Typing/Tired 姿态样本");
        Assert(tiredHeadY >= typingHeadY + 1.5, "WorkTired 必须真实下垂头部，而不只是换脸");
        Assert(yawnBodyScaleY >= 1.025, "Yawn 必须有身体伸展/吸气阶段，而不只是嘴型切换");
        Assert(annoyedTilt >= 1.5, "WorkAnnoyed 必须增加身体张力/前倾，而不只是眉眼嘴变化");
        Assert(tiredPawTravel >= 1.0, "WorkTired 必须保留更慢的连续打字节奏");
        Assert(annoyedPawTravel >= 2.0, "WorkAnnoyed 必须保留更快更重的连续错相打字节奏");
    }

    private static void VerifyTenMinuteEquivalentSoak()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 71, 70.0)
            ?? throw new InvalidOperationException("无法创建 soak Motion Engine");
        var previousX  = 70.0;
        var maxStep    = 0.0;

        for (var frame = 0; frame < 36_000; frame++)
        {
            var segment = (frame / 900) % 4;
            var input = CreateInput(
                segment == 2 ? "Working" : "Resting",
                segment is 0 or 2 ? 128.0 : 28.0,
                108.0);
            var rawDt = frame > 0 && frame % 600 == 0
                ? 0.08 + (((frame / 600) % 18) * 0.01)
                : 1.0 / 60.0;
            var pose = update.Invoke(engine, [rawDt, input])
                ?? throw new InvalidOperationException("soak 没有输出 Pose");

            var x = ReadDouble(pose, "StageX");
            Assert(double.IsFinite(x), "36,000 帧 soak 出现非有限 StageX");
            Assert(x >= 19.99 && x <= 140.01, "36,000 帧 soak 越过舞台边界");
            AssertPoseFinite(pose, "Body");
            AssertPoseFinite(pose, "Head");
            AssertPoseFinite(pose, "TailTip");

            maxStep   = Math.Max(maxStep, Math.Abs(x - previousX));
            previousX = x;
        }

        Assert(maxStep < 4.1, "stall 后出现单帧 teleport；deltaTime clamp 失效");
    }

    private static void VerifyReleaseBundlesV2Assets()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "windows", "desktop", "scripts", "Build-Phase2WindowsRelease.ps1");
        var code = File.ReadAllText(path);

        Assert(code.Contains("assets\\maotai\\v2", StringComparison.Ordinal),
            "Windows release builder 尚未复制正式 maotai/v2 资产");
        Assert(code.Contains("ui-assets\\maotai\\v2", StringComparison.Ordinal),
            "Windows release payload 尚未携带 maotai/v2 独立透明资产");
    }

    private static object CreateInput(string baseState, double targetX, double workAnchorX)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
            0.15,
            -0.05,
            true,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            targetX,
            false,
            false,
            workAnchorX)
            ?? throw new InvalidOperationException("无法创建 MaotaiMotionInput");
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

    private static double ReadPoseDouble(object frame, string poseProperty, string valueProperty)
    {
        var pose = RequireProperty(frame.GetType(), poseProperty).GetValue(frame)
            ?? throw new InvalidOperationException($"PoseFrame 缺少 {poseProperty}");
        return ReadDouble(pose, valueProperty);
    }

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static void AssertPoseFinite(object frame, string propertyName)
    {
        var pose = RequireProperty(frame.GetType(), propertyName).GetValue(frame)
            ?? throw new InvalidOperationException($"PoseFrame 缺少 {propertyName}");
        Assert(double.IsFinite(ReadDouble(pose, "X")), $"{propertyName}.X 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "Y")), $"{propertyName}.Y 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "RotationDeg")), $"{propertyName}.RotationDeg 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "ScaleX")), $"{propertyName}.ScaleX 非有限值");
        Assert(double.IsFinite(ReadDouble(pose, "ScaleY")), $"{propertyName}.ScaleY 非有限值");
    }

    private static string FindRepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory);
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        for (var directory = new DirectoryInfo(Directory.GetCurrentDirectory());
             directory is not null;
             directory = directory.Parent)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, "windows", "desktop")) &&
                File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
            {
                return directory.FullName;
            }
        }

        throw new DirectoryNotFoundException("无法定位 PicotooPet 仓库根目录。");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
