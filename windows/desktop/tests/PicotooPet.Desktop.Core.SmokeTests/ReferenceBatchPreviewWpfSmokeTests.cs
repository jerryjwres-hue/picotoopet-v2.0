using System.Runtime.ExceptionServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class ReferenceBatchPreviewWpfSmokeTests
{
    public static void Run()
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            var frame = new DispatcherFrame();
            Dispatcher.CurrentDispatcher.BeginInvoke(new Action(async () =>
            {
                try { await VerifyAsync(); }
                catch (Exception exception) { failure = exception; }
                finally { frame.Continue = false; }
            }));
            Dispatcher.PushFrame(frame);
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private static async Task VerifyAsync()
    {
        // Catches replacing the native selection/consent surface with a placeholder.
        var panel = new ReferenceBatchPreviewPanel();
        panel.Measure(new Size(1000, 700));
        panel.Arrange(new Rect(0, 0, 1000, 700));
        panel.UpdateLayout();
        SmokeAssert.True(panel.FindName("ShotComboBox") is ComboBox, "Reference shot selection is missing");
        SmokeAssert.True(panel.FindName("SourceComboBox") is ComboBox, "Explicit source declaration is missing");
        SmokeAssert.True(panel.FindName("SourceDigestTextBox") is TextBox, "Licensed-source digest input is missing");
        SmokeAssert.True(panel.FindName("ChooseReferenceButton") is Button, "Native file selection is missing");
        SmokeAssert.True(panel.FindName("PreviewItems") is ItemsControl, "Real reference preview list is missing");
        var consent = panel.FindName("ConsentCheckBox") as CheckBox
            ?? throw new InvalidOperationException("Explicit preview and rights consent is missing");
        SmokeAssert.True(consent.IsChecked != true, "Rights consent must start unchecked");
        SmokeAssert.True(panel.FindName("SubmitBatchButton") is Button, "Batch request action is missing");
        SmokeAssert.True(panel.FindName("RefreshBatchButton") is Button, "Receipt refresh action is missing");
        SmokeAssert.True(panel.FindName("OpenApprovalsButton") is Button, "Existing approvals navigation is missing");

        // Catches a decoder stub or accepting extension alone instead of actual image bytes.
        var bitmap = BitmapSource.Create(2, 1, 96, 96, PixelFormats.Bgra32, null,
            new byte[] { 0, 0, 255, 255, 0, 255, 0, 255 }, 8);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        var preview = await ReferenceBatchPreviewViewModel.DecodePreviewAsync(stream.ToArray(), ".png");
        SmokeAssert.Equal(2, preview.PixelWidth, "Preview must decode real PNG pixels");
        SmokeAssert.Equal(1, preview.PixelHeight, "Preview dimensions changed");
        SmokeAssert.True(preview.IsFrozen, "Preview bitmap must be frozen for safe binding");
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(stream.ToArray(), ".webp"));
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(new byte[] { 1, 2, 3 }, ".png"));
    }

    private static async Task RejectAsync(Func<Task> operation)
    {
        try { await operation(); }
        catch (Exception exception) when (exception is not NotImplementedException) { return; }
        throw new InvalidOperationException("Invalid image must fail closed");
    }
}
