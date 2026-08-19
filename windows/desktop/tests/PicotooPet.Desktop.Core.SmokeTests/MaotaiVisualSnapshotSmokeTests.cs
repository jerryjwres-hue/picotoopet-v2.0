using System.Reflection;
using System.Text.Json;
using System.Windows;
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

        var snapshots = new[]
        {
            Capture(root, "idle",  "Resting", 72.0, wantsRun: false, frames: 12),
            Capture(root, "work",  "Working", 70.0, wantsRun: false, frames: 150),
            Capture(root, "sleep", "Offline", 72.0, wantsRun: false, frames: 150),
            Capture(root, "run",   "Resting", 138.0, wantsRun: true, frames: 90),
        };

        File.WriteAllText(
            Path.Combine(root, "maotai-visual-snapshot.json"),
            JsonSerializer.Serialize(snapshots, SnapshotJsonOptions));
    }

    private static SnapshotEvidence Capture(
        string root,
        string label,
        string baseState,
        double targetX,
        bool wantsRun,
        int frames)
    {
        var panel = new AssistantPetPanel
        {
            IsFloatingMode = true,
            Width = 260,
            Height = 240,
            Background = Brushes.Transparent,
        };

        Layout(panel);
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

        apply.Invoke(renderer, [frame]);
        Layout(panel);

        var fileName = $"maotai-{label}.png";
        var path = Path.Combine(root, fileName);
        SaveVisual(panel, path);

        var state = ReadProperty(frame, "State")?.ToString() ?? "Unknown";
        return new SnapshotEvidence(label, state, fileName, 260, 240);
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

    private sealed record SnapshotEvidence(
        string Label,
        string MotionState,
        string FileName,
        int Width,
        int Height);
}
