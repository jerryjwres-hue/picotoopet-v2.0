using System.Reflection;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>只读视觉验收入口：用真实 WPF Rig/Renderer 输出确定性截图，不写 Core/Worker/Task/Approval。</summary>
internal static class MaotaiVisualSnapshotSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;
    private static readonly Type PanelType = typeof(AssistantPetPanel);
    private static readonly JsonSerializerOptions SnapshotJsonOptions = new()
    {
        WriteIndented = true,
    };

    public static void Run(string outputDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(outputDirectory);
        var root = Path.GetFullPath(outputDirectory);
        Directory.CreateDirectory(root);
        Log("run:start");

        // Sampling contract   : each label must freeze the advertised live state, not a later stopped frame.
        // Offline needs longer : Sleep traverses Sit -> LieDown -> Sleep, so give the real graph six seconds.
        var snapshots = new[]
        {
            Capture(root, "idle",  "Resting", 72.0, wantsRun: false, frames: 12),
            Capture(root, "work",  "Working", 70.0, wantsRun: false, frames: 150),
            Capture(root, "sleep", "Offline", 72.0, wantsRun: false, frames: 360),
            Capture(root, "run",   "Resting", 138.0, wantsRun: true, frames: 30),
        };

        Log("json:write");
        File.WriteAllText(
            Path.Combine(root, "maotai-visual-snapshot.json"),
            JsonSerializer.Serialize(snapshots, SnapshotJsonOptions));
        Log("run:done");
    }

    private static SnapshotEvidence Capture(
        string root,
        string label,
        string baseState,
        double targetX,
        bool wantsRun,
        int frames)
    {
        Log($"{label}:panel-create");
        var panel = new AssistantPetPanel
        {
            IsFloatingMode = true,
            Width = 260,
            Height = 240,
            Background = Brushes.Transparent,
        };

        Log($"{label}:layout-1");
        Layout(panel);
        Log($"{label}:rig-init");
        InvokePanel(panel, "EnsureMaotaiV2Initialized");
        InvokePanel(panel, "StopMaotaiRendering");

        var ready = (bool)(RequirePanelField("_maotaiRigReady").GetValue(panel) ?? false);
        if (!ready)
        {
            throw new InvalidOperationException(
                $"Maotai visual snapshot '{label}' 无法初始化完整 v2 Rig");
        }

        var engine = RequirePanelField("_maotaiMotionEngine").GetValue(panel)
            ?? throw new InvalidOperationException("Maotai visual snapshot 缺少 MotionEngine");
        var renderer = RequirePanelField("_maotaiRenderer").GetValue(panel)
            ?? throw new InvalidOperationException("Maotai visual snapshot 缺少 RasterRenderer");
        var update = engine.GetType().GetMethod(
            "Update",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 Update");
        var apply = renderer.GetType().GetMethod(
            "Apply",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiRasterRenderer 缺少 Apply");

        Log($"{label}:engine-update");
        var input = CreateInput(baseState, targetX, wantsRun);
        object? frame = null;
        for (var index = 0; index < frames; index++)
        {
            frame = update.Invoke(engine, [1.0 / 60.0, input]);
        }
        if (frame is null)
        {
            throw new InvalidOperationException($"Maotai visual snapshot '{label}' 没有生成 PoseFrame");
        }

        var motionState = ReadProperty(frame, "MotionState")?.ToString() ?? "Unknown";
        VerifyExpectedMotionState(label, motionState);

        Log($"{label}:renderer-apply");
        apply.Invoke(renderer, [frame]);
        VerifyWorkAccessoryVisibility(panel, label, expectedVisible: baseState == "Working");
        VerifyPoseCohesionVisibility(panel, label);
        if (baseState == "Working")
        {
            VerifyWorkPropLayout(panel);
        }
        Layout(panel);

        var fileName = $"maotai-{label}.png";
        var path = Path.Combine(root, fileName);
        Log($"{label}:bitmap-render");
        SaveVisual(panel, path);
        Log($"{label}:saved");

        return new SnapshotEvidence(label, motionState, fileName, 260, 240);
    }

    private static void VerifyExpectedMotionState(string label, string motionState)
    {
        var valid = label switch
        {
            "idle"  => motionState is "Idle" or "Look",
            "work"  => motionState is "WorkSettle" or "WorkTyping" or "WorkTired" or "Yawn" or "WorkAnnoyed" or "Recover",
            "sleep" => motionState == "Sleep",
            "run"   => motionState == "Run",
            _       => false,
        };
        if (!valid)
        {
            throw new InvalidOperationException(
                $"Maotai visual snapshot '{label}' 捕获了错误动作状态；actual={motionState}");
        }
    }

    private static void VerifyWorkAccessoryVisibility(
        AssistantPetPanel panel,
        string label,
        bool expectedVisible)
    {
        var expected = expectedVisible ? 1.0 : 0.0;
        foreach (var name in new[]
                 {
                     "MaotaiV2HeadphoneBand",
                     "MaotaiV2HeadphoneLeft",
                     "MaotaiV2HeadphoneRight",
                 })
        {
            var element = panel.FindName(name) as FrameworkElement
                ?? throw new InvalidOperationException($"Maotai visual snapshot 缺少 {name}");
            if (Math.Abs(element.Opacity - expected) > 0.000001)
            {
                throw new InvalidOperationException(
                    $"Maotai visual snapshot '{label}' 的 {name} 显隐错误；expected={expected:F1}, actual={element.Opacity:F1}");
            }
        }
    }

    private static void VerifyPoseCohesionVisibility(AssistantPetPanel panel, string label)
    {
        // Front-view occlusion  : moving rear limbs sit behind the torso/front pair instead of creating detached side pieces.
        // Folded rest/work      : work/sleep continue to tuck all long upper segments behind the plush torso.
        var hideFrontUpper = label is "work" or "sleep";
        var hideRearUpper  = label is "work" or "sleep" or "run";

        foreach (var name in new[]
                 {
                     "MaotaiV2FrontLeftUpper",
                     "MaotaiV2FrontRightUpper",
                 })
        {
            AssertOpacity(panel, label, name, hideFrontUpper ? 0.0 : 1.0, "前腿连续主轮廓");
        }

        foreach (var name in new[]
                 {
                     "MaotaiV2HindLeftUpper",
                     "MaotaiV2HindRightUpper",
                 })
        {
            AssertOpacity(panel, label, name, hideRearUpper ? 0.0 : 1.0, "前视后腿遮挡");
        }

        foreach (var name in new[]
                 {
                     "MaotaiV2FrontLeftLower",
                     "MaotaiV2FrontRightLower",
                     "MaotaiV2HindLeftLower",
                     "MaotaiV2HindRightLower",
                 })
        {
            AssertOpacity(panel, label, name, 0.0, "禁止上下腿横向拼接缝");
        }

        AssertOpacity(panel, label, "MaotaiV2FrontLeftPaw",  1.0, "前脚接触点");
        AssertOpacity(panel, label, "MaotaiV2FrontRightPaw", 1.0, "前脚接触点");
        var rearPawOpacity = label == "run" ? 0.0 : 1.0;
        AssertOpacity(panel, label, "MaotaiV2HindLeftPaw",  rearPawOpacity, "前视后脚遮挡");
        AssertOpacity(panel, label, "MaotaiV2HindRightPaw", rearPawOpacity, "前视后脚遮挡");
    }

    private static void AssertOpacity(
        AssistantPetPanel panel,
        string label,
        string name,
        double expected,
        string contract)
    {
        var element = panel.FindName(name) as FrameworkElement
            ?? throw new InvalidOperationException($"Maotai visual snapshot 缺少 {name}");
        if (Math.Abs(element.Opacity - expected) > 0.000001)
        {
            throw new InvalidOperationException(
                $"Maotai visual snapshot '{label}' 的 {name} {contract}；" +
                $"expected={expected:F1}, actual={element.Opacity:F1}");
        }
    }

    private static void VerifyWorkPropLayout(AssistantPetPanel panel)
    {
        var laptop = panel.FindName("MaotaiV2Laptop") as FrameworkElement
            ?? throw new InvalidOperationException("Maotai visual snapshot 缺少 MaotaiV2Laptop");
        var laptopLeft = Canvas.GetLeft(laptop);
        if (!double.IsFinite(laptopLeft) || Math.Abs(laptopLeft - 68.0) > 0.000001)
        {
            throw new InvalidOperationException(
                $"Maotai work laptop 必须对齐双爪键盘区；expected left=68.0, actual={laptopLeft:F1}");
        }
    }

    private static object CreateInput(string baseState, double targetX, bool wantsRun)
    {
        var inputType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var baseStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        return Activator.CreateInstance(
            inputType,
            [
                Enum.Parse(baseStateType, baseState),
                0.0,
                0.0,
                false,
                Enum.Parse(interactionType, "None"),
                18.0,
                150.0,
                targetX,
                wantsRun,
                false,
                70.0,
            ]) ?? throw new InvalidOperationException("无法创建 MaotaiMotionInput");
    }

    private static void SaveVisual(FrameworkElement visual, string path)
    {
        const int width = 260;
        const int height = 240;
        var bitmap = new RenderTargetBitmap(
            width,
            height,
            96.0,
            96.0,
            PixelFormats.Pbgra32);
        bitmap.Render(visual);
        bitmap.Freeze();

        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = File.Create(path);
        encoder.Save(stream);
        if (stream.Length <= 128)
        {
            throw new InvalidOperationException($"Maotai visual snapshot '{path}' 输出为空");
        }
    }

    private static void Layout(FrameworkElement panel)
    {
        var size = new Size(260, 240);
        panel.Measure(size);
        panel.Arrange(new Rect(new Point(0, 0), size));
        panel.UpdateLayout();
    }

    private static void InvokePanel(object panel, string methodName)
    {
        var method = PanelType.GetMethod(
            methodName,
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException($"AssistantPetPanel 缺少 {methodName}");
        method.Invoke(panel, null);
    }

    private static FieldInfo RequirePanelField(string fieldName) =>
        PanelType.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少字段 {fieldName}");

    private static Type RequireType(string typeName) =>
        DesktopAssembly.GetType(typeName, throwOnError: true)!;

    private static object? ReadProperty(object target, string propertyName) =>
        target.GetType().GetProperty(
            propertyName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target);

    private static void Log(string stage) =>
        Console.WriteLine($"MAOTAI_SNAPSHOT_STAGE={stage}");

    private sealed record SnapshotEvidence(
        string Label,
        string MotionState,
        string FileName,
        int Width,
        int Height);
}