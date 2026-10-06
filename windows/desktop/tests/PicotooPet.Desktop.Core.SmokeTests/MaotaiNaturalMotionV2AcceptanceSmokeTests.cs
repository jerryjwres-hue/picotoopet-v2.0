using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 后半程的资产、全身姿态、锁脚和长时间稳定性合同。</summary>
internal static class MaotaiNaturalMotionV2AcceptanceSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyAllFeetExposeLockTelemetry();
        VerifyAllFourFeetLockDuringSupport();
        VerifyTurnAnticipationPreventsInstantMirror();
        VerifyNaturalWorkPosture();
        VerifyTenMinuteEquivalentSoak();
        VerifyReleaseBundlesV2Assets();
        VerifyFloatingPetReusesMotionEngine();
        VerifyIndependentAssetGate();
    }

    private static void VerifyIndependentAssetGate()
    {
        var manifestType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAssetManifest");
        var tryGet       = manifestType.GetMethod(
            "TryGetDescriptor",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new InvalidOperationException("v2 资产 manifest 缺少 TryGetDescriptor 元数据 Gate");
        var root      = FindRepositoryRoot();
        var assetRoot = Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "Assets",
            "Maotai",
            "V2");

        string[] requiredAssets =
        [
            "torso_neutral.png", "torso_crouch.png", "torso_stretch.png", "chest_fur.png",
            "head.png", "muzzle.png", "ear_left.png", "ear_right.png",
            "eye_left_open.png", "eye_right_open.png", "eye_left_half.png", "eye_right_half.png",
            "eye_left_closed.png", "eye_right_closed.png", "pupil_left.png", "pupil_right.png",
            "brow_left.png", "brow_right.png",
            "mouth_smile.png", "mouth_tired.png", "mouth_annoyed.png", "mouth_yawn.png", "mouth_tongue.png",
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
            var width   = ReadDouble(descriptor, "Width");
            var height  = ReadDouble(descriptor, "Height");
            var pivotX  = ReadDouble(descriptor, "PivotX");
            var pivotY  = ReadDouble(descriptor, "PivotY");
            var overlap = ReadDouble(descriptor, "JointOverlapPixels");

            Assert(width > 0.0 && height > 0.0, $"v2 资产逻辑尺寸非法：{fileName}");
            Assert(pivotX >= 0.0 && pivotX <= width && pivotY >= 0.0 && pivotY <= height,
                $"v2 资产 Pivot 越界：{fileName}");
            Assert(overlap >= 12.0, $"v2 关节隐藏重叠区不足 12px：{fileName}");

            var pngPath = Path.Combine(assetRoot, fileName);
            Assert(File.Exists(pngPath), $"v2 正式独立透明资产尚未交付：{fileName}");
            VerifyTransparentPng(pngPath, fileName);
        }

        var actualPngs = Directory.Exists(assetRoot)
            ? Directory.GetFiles(assetRoot, "*.png", SearchOption.TopDirectoryOnly)
            : [];
        Assert(actualPngs.Length == requiredAssets.Length,
            "v2 正式资产目录必须只包含 manifest 规定的独立 PNG，禁止额外整图状态素材");
    }

    private static void VerifyTransparentPng(string path, string fileName)
    {
        var header = new byte[33];
        using var stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        Assert(stream.Length > header.Length, $"v2 PNG 文件过小或损坏：{fileName}");
        Assert(stream.Read(header, 0, header.Length) == header.Length, $"v2 PNG 头读取失败：{fileName}");

        byte[] signature = [137, 80, 78, 71, 13, 10, 26, 10];
        for (var index = 0; index < signature.Length; index++)
        {
            Assert(header[index] == signature[index], $"v2 资产不是有效 PNG：{fileName}");
        }

        Assert(header[12] == (byte)'I' &&
               header[13] == (byte)'H' &&
               header[14] == (byte)'D' &&
               header[15] == (byte)'R',
            $"v2 PNG 缺少 IHDR：{fileName}");

        var pixelWidth  = ReadBigEndianUInt32(header, 16);
        var pixelHeight = ReadBigEndianUInt32(header, 20);
        var colorType   = header[25];
        Assert(pixelWidth >= 12 && pixelHeight >= 12, $"v2 PNG 像素尺寸过小：{fileName}");
        Assert(colorType is 4 or 6, $"v2 PNG 必须自带 alpha 通道，禁止扁平背景图：{fileName}");
    }

    private static uint ReadBigEndianUInt32(byte[] buffer, int offset) =>
        ((uint)buffer[offset] << 24) |
        ((uint)buffer[offset + 1] << 16) |
        ((uint)buffer[offset + 2] << 8) |
        buffer[offset + 3];

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

    private static void VerifyAllFourFeetLockDuringSupport()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 47, 38.0)
            ?? throw new InvalidOperationException("无法创建四足锁脚 Motion Engine");

        string[] supportProperties =
        [
            "FrontLeftSupport",
            "FrontRightSupport",
            "HindLeftSupport",
            "HindRightSupport",
        ];
        string[] worldXProperties =
        [
            "FrontLeftPawWorldX",
            "FrontRightPawWorldX",
            "HindLeftPawWorldX",
            "HindRightPawWorldX",
        ];
        var previousWorldX = new[] { double.NaN, double.NaN, double.NaN, double.NaN };
        var previousSupport = new bool[4];
        var observedSupport = new bool[4];
        var maximumDrift    = new double[4];

        for (var frame = 0; frame < 900; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateInput("Resting", 132.0, 108.0)])
                ?? throw new InvalidOperationException("四足锁脚测试没有输出 Pose");

            for (var foot = 0; foot < supportProperties.Length; foot++)
            {
                var support = ReadBool(pose, supportProperties[foot]);
                if (!support)
                {
                    previousSupport[foot] = false;
                    previousWorldX[foot]  = double.NaN;
                    continue;
                }

                observedSupport[foot] = true;
                var worldX = ReadDouble(pose, worldXProperties[foot]);
                Assert(double.IsFinite(worldX), $"第 {foot + 1} 只脚支撑相世界坐标非有限值");
                if (previousSupport[foot])
                {
                    maximumDrift[foot] = Math.Max(
                        maximumDrift[foot],
                        Math.Abs(worldX - previousWorldX[foot]));
                }

                previousSupport[foot] = true;
                previousWorldX[foot]  = worldX;
            }
        }

        for (var foot = 0; foot < observedSupport.Length; foot++)
        {
            Assert(observedSupport[foot], $"第 {foot + 1} 只脚从未进入支撑相");
            Assert(maximumDrift[foot] < 0.75, $"第 {foot + 1} 只脚支撑相世界漂移过大：{maximumDrift[foot]:F3}");
        }
    }

    private static void VerifyTurnAnticipationPreventsInstantMirror()
    {
        var controllerType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiLocomotionController");
        var update         = controllerType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("Locomotion 缺少 Update");
        var controller     = Activator.CreateInstance(controllerType, 70.0)
            ?? throw new InvalidOperationException("无法创建 Locomotion Controller");

        for (var frame = 0; frame < 20; frame++)
        {
            update.Invoke(controller, [1.0 / 60.0, 138.0, true, false, 20.0, 140.0]);
        }

        var beforeReverseVelocity = ReadDouble(controller, "VelocityX");
        Assert(beforeReverseVelocity > 20.0, "反向预备测试没有建立向右惯性");

        update.Invoke(controller, [1.0 / 60.0, 22.0, true, false, 20.0, 140.0]);
        var velocityAfterReverse = ReadDouble(controller, "VelocityX");
        var facingAfterReverse   = ReadInt(controller, "FacingSign");
        var anticipation         = ReadDouble(controller, "TurnAnticipation");

        Assert(velocityAfterReverse > 5.0, "反向第一帧不应瞬间消除全部惯性");
        Assert(facingAfterReverse == 1, "身体仍向右滑动时禁止整套 Raster Skeleton 瞬间镜像");
        Assert(anticipation < -0.01, "反向请求必须先产生左转 anticipation 张力");

        var flipped = false;
        for (var frame = 0; frame < 90; frame++)
        {
            update.Invoke(controller, [1.0 / 60.0, 22.0, true, false, 20.0, 140.0]);
            if (ReadInt(controller, "FacingSign") == -1)
            {
                flipped = true;
                break;
            }
        }

        Assert(flipped, "减速进入低速区后必须完成方向翻转");
    }

    private static void VerifyNaturalWorkPosture()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 53, 108.0)
            ?? throw new InvalidOperationException("无法创建工作姿态 Motion Engine");

        var typingHeadY         = double.NaN;
        var tiredHeadY          = double.NaN;
        var yawnBodyScaleY      = double.NaN;
        var annoyedTilt         = double.NaN;
        var tiredPawTravel      = 0.0;
        var annoyedPawTravel    = 0.0;
        var previousTiredPawY   = double.NaN;
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
        var previousX = 70.0;
        var maxStep   = 0.0;

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
        var root    = FindRepositoryRoot();
        var project = Path.Combine(
            root,
            "windows",
            "desktop",
            "src",
            "PicotooPet.Desktop",
            "PicotooPet.Desktop.csproj");
        var code = File.ReadAllText(project);

        Assert(code.Contains("Assets\\Maotai\\V2\\**\\*.png", StringComparison.Ordinal),
            "Windows publish 尚未声明正式 maotai/v2 独立 PNG 源");
        Assert(code.Contains("ui-assets\\maotai\\v2", StringComparison.Ordinal),
            "Windows publish 尚未把 maotai/v2 映射到 installer payload 固定目录");
        Assert(code.Contains("<CopyToPublishDirectory>Always</CopyToPublishDirectory>", StringComparison.Ordinal),
            "Windows publish 必须强制携带 maotai/v2 正式资产");
    }

    private static void VerifyFloatingPetReusesMotionEngine()
    {
        var root     = FindRepositoryRoot();
        var xamlPath = Path.Combine(root, "windows", "desktop", "src", "PicotooPet.Desktop", "Views", "FloatingPetWindow.xaml");
        var codePath = Path.Combine(root, "windows", "desktop", "src", "PicotooPet.Desktop", "Views", "FloatingPetWindow.xaml.cs");
        var xaml     = File.ReadAllText(xamlPath);
        var code     = File.ReadAllText(codePath);

        Assert(xaml.Contains("<controls:AssistantPetPanel", StringComparison.Ordinal),
            "Floating Pet 必须直接复用 AssistantPetPanel 的同一 Motion Engine 模型");
        Assert(!code.Contains("new MaotaiMotionEngine", StringComparison.Ordinal) &&
               !code.Contains("DispatcherTimer", StringComparison.Ordinal),
            "FloatingPetWindow 禁止复制第二套茅台状态机或低频动作计时器");
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

    private static bool ReadBool(object value, string propertyName) =>
        (bool)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static int ReadInt(object value, string propertyName) =>
        (int)(RequireProperty(value.GetType(), propertyName).GetValue(value)
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
