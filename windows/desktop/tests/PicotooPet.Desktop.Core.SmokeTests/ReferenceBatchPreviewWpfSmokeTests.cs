using System.Runtime.ExceptionServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;

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
        var wide = BitmapSource.Create(8193, 1, 96, 96, PixelFormats.Bgra32, null, new byte[8193 * 4], 8193 * 4);
        var wideEncoder = new PngBitmapEncoder();
        wideEncoder.Frames.Add(BitmapFrame.Create(wide));
        using var wideStream = new MemoryStream();
        wideEncoder.Save(wideStream);
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(wideStream.ToArray(), ".png"));
        await VerifyBatchStateAsync(stream.ToArray());
    }

    private static async Task VerifyBatchStateAsync(byte[] png)
    {
        var root = Path.Combine(Path.GetTempPath(), "reference-preview-smoke-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var source = Path.Combine(root, "source.png");
            await File.WriteAllBytesAsync(source, png);
            var policy = new ReferencePreviewFilePolicy(ProductionLocalEnvironment.ResolveUnderRoot,
                ProductionLocalEnvironment.AssertNoLinkEscape, ProductionLocalEnvironment.IsOrdinaryFile,
                ProductionLocalEnvironment.Sha256FileAsync);
            var stager = new ReferencePreviewSnapshotStager(root, policy, ReferenceBatchPreviewViewModel.ValidateImageAsync);
            var gateway = new RecordingGateway();
            var vm = new ReferenceBatchPreviewViewModel(gateway, stager, Continuation(), Package());
            SmokeAssert.Equal(1, vm.EligibleShots.Length, "Only IMAGE_TO_VIDEO shots from the frozen plan are eligible");
            SmokeAssert.Equal("shot-1", vm.EligibleShots[0], "Wrong frozen shot selected");
            await RejectAsync(() => vm.AddAsync("text-shot", source, "USER_SUPPLIED", null));
            await RejectAsync(() => vm.AddAsync("shot-1", source, "LICENSED", null));
            SmokeAssert.Equal(0, vm.Items.Count, "Rejected source declarations must not appear as eligible references");
            await vm.AddAsync("shot-1", source, "USER_SUPPLIED", null);
            SmokeAssert.Equal(1, vm.Items.Count, "Staged reference must appear in the actual preview collection");
            SmokeAssert.Equal(vm.Items[0].Sha256, vm.Items[0].SourceDigest, "User supplied source digest must bind the exact staged bytes");
            SmokeAssert.True(vm.Items[0].Preview.IsFrozen, "Actual selected reference needs a frozen real image");
            var panel = new ReferenceBatchPreviewPanel(vm);
            panel.Measure(new Size(1000, 700));
            panel.Arrange(new Rect(0, 0, 1000, 700));
            panel.UpdateLayout();
            Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            SmokeAssert.Equal(1, ((ItemsControl)panel.FindName("PreviewItems")).Items.Count,
                "WPF preview list must bind to staged images");
            SmokeAssert.True(!((Button)panel.FindName("SubmitBatchButton")).IsEnabled,
                "Submit must stay disabled before explicit preview and rights consent");
            await RejectAsync(() => vm.SubmitAsync());
            SmokeAssert.Equal(0, gateway.RegisterCalls, "No request may reach Core without explicit consent");
            ((CheckBox)panel.FindName("ConsentCheckBox")).IsChecked = true;
            Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            SmokeAssert.True(vm.UserConfirmsPreviewAndRights, "Consent must bind from actual WPF control");
            var pending = new TaskCompletionSource<ReferenceBatchReceipt>();
            gateway.Pending = pending;
            var submit = vm.SubmitAsync();
            await vm.SubmitAsync();
            SmokeAssert.Equal(1, gateway.RegisterCalls, "Double submit must share one in-flight request");
            await RejectAsync(() => vm.AddAsync("shot-1", source, "USER_SUPPLIED", null));
            pending.SetResult(gateway.CreateReceipt());
            await submit;
            SmokeAssert.Equal("Pending", vm.Receipt!.Status, "Core pending receipt must be rendered without autoapproval");
            await vm.SubmitAsync();
            SmokeAssert.Equal(1, gateway.RegisterCalls, "Submit after receipt must refresh rather than register again");
            SmokeAssert.Equal(1, gateway.GetCalls, "Submit after receipt must fetch the durable receipt");

            // An unknown POST outcome locks edits and retries the exact same canonical payload/key.
            var uncertainGateway = new RecordingGateway { FailNextPost = true };
            var uncertain = new ReferenceBatchPreviewViewModel(uncertainGateway, stager, Continuation(), Package());
            await uncertain.AddAsync("shot-1", source, "USER_SUPPLIED", null);
            uncertain.UserConfirmsPreviewAndRights = true;
            await RejectAsync(() => uncertain.SubmitAsync());
            SmokeAssert.True(!uncertain.CanEdit, "Ambiguous POST outcome must permanently freeze the chosen payload");
            await RejectAsync(() => Task.Run(() => uncertain.Remove("shot-1")));
            var originalKey = uncertainGateway.LastKey;
            await uncertain.SubmitAsync();
            SmokeAssert.Equal(originalKey, uncertainGateway.LastKey, "Ambiguous retry changed the deterministic idempotency key");

            var staged = Path.Combine(root, vm.Items[0].InputRelativePath.Replace('/', Path.DirectorySeparatorChar));
            await File.WriteAllBytesAsync(staged, new byte[] { 1, 2, 3 });
            await RejectAsync(() => vm.RefreshAsync());
            SmokeAssert.Equal(1, gateway.GetCalls, "Changed staged bytes must prevent even receipt refresh");
            await RejectAsync(() => vm.AddAsync("text-shot", source, "USER_SUPPLIED", null));
            var bad = Package() with { QualityOutcome = "FAIL" };
            await RejectAsync(() => Task.Run(() => new ReferenceBatchPreviewViewModel(gateway, stager, Continuation(), bad)));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static GoalVideoContinuationRecord Continuation() => new("11111111-1111-4111-8111-111111111111", new string('a', 64),
        new string('b', 64), "job-1", "22222222-2222-4222-8222-222222222222", new string('c', 64), "creative_ready", null, null);

    private static CreativePackageRecord Package() => new("22222222-2222-4222-8222-222222222222", "job-1", new string('d', 64),
        new string('c', 64), "packages/package-1.zip", JsonDocument.Parse("""
        {"creative_package_id":"22222222-2222-4222-8222-222222222222","creative_job_id":"job-1","quality_outcome":"PASS",
         "source_set_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
         "stage_results":{"shot_plan.v1":{"shots":[{"shot_id":"shot-1","render_intent":"IMAGE_TO_VIDEO"},
         {"shot_id":"text-shot","render_intent":"TEXT_TO_VIDEO"}]}}}
        """).RootElement.Clone(), "PASS", DateTimeOffset.UtcNow);

    private sealed class RecordingGateway : IReferenceBatchGateway
    {
        public int RegisterCalls { get; private set; }
        public int GetCalls { get; private set; }
        public bool FailNextPost { get; set; }
        public string? LastKey { get; private set; }
        public ReferenceBatchRequest? Request { get; private set; }
        public TaskCompletionSource<ReferenceBatchReceipt>? Pending { get; set; }

        public Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(ReferenceBatchRequest request,
            string key, CancellationToken cancellationToken)
        {
            RegisterCalls++;
            Request = request;
            LastKey = key;
            if (FailNextPost)
            {
                FailNextPost = false;
                return Task.FromException<ReferenceBatchReceipt>(new IOException("unknown network outcome"));
            }
            return Pending?.Task ?? Task.FromResult(CreateReceipt());
        }
        public Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken)
        {
            GetCalls++;
            SmokeAssert.Equal("44444444-4444-4444-8444-444444444444", approvalId, "Refresh must address approval_id, not batch_id");
            return Task.FromResult(CreateReceipt());
        }
        public ReferenceBatchReceipt CreateReceipt()
        {
            var request = Request ?? throw new InvalidOperationException("No request");
            var json = JsonSerializer.Serialize(new
            {
                schema_version = "reference_batch.v1", batch_id = "33333333-3333-4333-8333-333333333333",
                approval_id = "44444444-4444-4444-8444-444444444444",
                approval_request_digest = new string('e', 64), status = "Pending",
                expires_at = DateTimeOffset.UtcNow.AddMinutes(30), goal_id = request.GoalId,
                creative_package_id = request.CreativePackageId, creative_package_digest = request.CreativePackageDigest,
                references = request.SelectedReferences.Select(x => new { asset_id = "55555555-5555-4555-8555-555555555555", shot_id = x.ShotId,
                    input_relative_path = x.InputRelativePath, sha256 = x.Sha256, bytes = x.Bytes,
                    source_reference = x.SourceReference, source_digest = x.SourceDigest })
            });
            return JsonSerializer.Deserialize<ReferenceBatchReceipt>(json)!;
        }
    }

    private static async Task RejectAsync(Func<Task> operation)
    {
        try { await operation(); }
        catch (Exception exception) when (exception is not NotImplementedException) { return; }
        throw new InvalidOperationException("Invalid image must fail closed");
    }
}
