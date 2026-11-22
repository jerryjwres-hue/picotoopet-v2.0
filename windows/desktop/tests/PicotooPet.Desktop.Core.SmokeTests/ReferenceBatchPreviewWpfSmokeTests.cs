using System.Runtime.ExceptionServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
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
        var goalPanel = new GoalCenterPanel();
        var entry = goalPanel.FindName("ReferenceBatchPreviewButton") as Button
            ?? throw new InvalidOperationException("Goal Center reference preview entry is missing");
        SmokeAssert.Equal(Visibility.Collapsed, entry.Visibility, "Unready Goal Center must hide reference preview entry");
        // Catches replacing the native selection/consent surface with a placeholder.
        var panel = new ReferenceBatchPreviewPanel();
        panel.Measure(new Size(1000, 700));
        panel.Arrange(new Rect(0, 0, 1000, 700));
        panel.UpdateLayout();
        SmokeAssert.True(panel.FindName("ShotComboBox") is ComboBox, "Reference shot selection is missing");
        SmokeAssert.True(panel.FindName("SourceComboBox") is ComboBox, "Explicit source declaration is missing");
        SmokeAssert.True(panel.FindName("SourceDigestTextBox") is TextBox, "Licensed-source digest input is missing");
        SmokeAssert.True(panel.FindName("ChooseReferenceButton") is Button, "Native file selection is missing");
        SmokeAssert.True(panel.FindName("LoadObservedCandidatesButton") is Button,
            "Read-only Comfy candidate list import is missing");
        SmokeAssert.True(panel.FindName("RestoreReferenceBatchButton") is Button,
            "Existing approved batches must be recoverable after restart");
        SmokeAssert.True(panel.FindName("ResumeApprovalIdTextBox") is TextBox,
            "Existing approval ID input is missing");
        SmokeAssert.True(panel.FindName("ObservedCandidatesList") is ItemsControl,
            "Observed candidates cannot be reviewed in the existing UI");
        SmokeAssert.True(panel.FindName("PreviewItems") is ItemsControl, "Real reference preview list is missing");
        var consent = panel.FindName("ConsentCheckBox") as CheckBox
            ?? throw new InvalidOperationException("Explicit preview and rights consent is missing");
        SmokeAssert.True(consent.IsChecked != true, "Rights consent must start unchecked");
        SmokeAssert.True(panel.FindName("SubmitBatchButton") is Button, "Batch request action is missing");
        SmokeAssert.True(panel.FindName("RefreshBatchButton") is Button, "Receipt refresh action is missing");
        SmokeAssert.True(panel.FindName("OpenApprovalsButton") is Button, "Existing approvals navigation is missing");
        SmokeAssert.True(panel.FindName("CreateReviewedPlanButton") is Button { IsEnabled: false },
            "Plan creation must remain disabled before exact approval");
        var approvalsRequested = false;
        panel.ApprovalsRequested += (_, _) => approvalsRequested = true;
        ((Button)panel.FindName("OpenApprovalsButton")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        SmokeAssert.True(approvalsRequested, "Actual approvals button must request existing approvals navigation");

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
        var decodedPixels = new byte[8];
        preview.CopyPixels(decodedPixels, 8, 0);
        SmokeAssert.Equal((byte)255, decodedPixels[2], "Preview must contain the actual red source pixel");
        SmokeAssert.Equal((byte)255, decodedPixels[3], "Preview must retain source opacity");
        var jpeg = new JpegBitmapEncoder();
        jpeg.Frames.Add(BitmapFrame.Create(bitmap));
        using var jpegStream = new MemoryStream();
        jpeg.Save(jpegStream);
        var jpegPreview = await ReferenceBatchPreviewViewModel.DecodePreviewAsync(jpegStream.ToArray(), ".jpeg");
        SmokeAssert.Equal(2, jpegPreview.PixelWidth, "Actual JPEG must decode through its verified native codec");
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(stream.ToArray(), ".webp"));
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(new byte[] { 1, 2, 3 }, ".png"));
        var wide = BitmapSource.Create(8193, 1, 96, 96, PixelFormats.Bgra32, null, new byte[8193 * 4], 8193 * 4);
        var wideEncoder = new PngBitmapEncoder();
        wideEncoder.Frames.Add(BitmapFrame.Create(wide));
        using var wideStream = new MemoryStream();
        wideEncoder.Save(wideStream);
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(wideStream.ToArray(), ".png"));
        await VerifyBatchStateAsync(stream.ToArray());
        await VerifySealedV2SelectionAsync(stream.ToArray());
        Console.WriteLine("REFERENCE_PREVIEW_GUI_API=PASS; PNG_JPEG_PIXELS=PASS; GPU_POST=0");
        var codecs = Windows.Graphics.Imaging.BitmapDecoder.GetDecoderInformationEnumerator();
        Console.WriteLine("NATIVE_WEBP_CODEC_REGISTERED=" + codecs.Any(codec => codec.CodecId == Windows.Graphics.Imaging.BitmapDecoder.WebpDecoderId));
        // Google Skia resources/images/half-transparent-white-pixel.webp (38-byte known valid fixture).
        var webp = Convert.FromBase64String("UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAEAfQ//73v3+BiOh/AAA=");
        var webpPreview = await ReferenceBatchPreviewViewModel.DecodePreviewAsync(webp, ".webp");
        SmokeAssert.Equal(1, webpPreview.PixelWidth, "Actual WebP must decode through the bundled CPU codec");
        SmokeAssert.Equal(1, webpPreview.PixelHeight, "WebP fixture height changed");
        await RejectAsync(() => ReferenceBatchPreviewViewModel.DecodePreviewAsync(webp[..20], ".webp"));
        Console.WriteLine("REFERENCE_PREVIEW_WEBP=PASS; DECODER=BUNDLED_CPU");
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
            SmokeAssert.True(((Button)panel.FindName("SubmitBatchButton")).IsEnabled,
                "Actual submit button must enable only after explicit consent");
            var pending = new TaskCompletionSource<ReferenceBatchReceipt>();
            gateway.Pending = pending;
            var submit = vm.SubmitAsync();
            await gateway.RegisterEntered.Task.WaitAsync(TimeSpan.FromSeconds(15));
            await vm.SubmitAsync();
            SmokeAssert.Equal(1, gateway.RegisterCalls, "Double submit must share one in-flight request");
            await RejectAsync(() => vm.AddAsync("shot-1", source, "USER_SUPPLIED", null));
            pending.SetResult(gateway.CreateReceipt());
            await submit;
            SmokeAssert.Equal("Pending", vm.Receipt!.Status, "Core pending receipt must be rendered without autoapproval");
            Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            SmokeAssert.True(!((CheckBox)panel.FindName("ConsentCheckBox")).IsEnabled,
                "Actual consent control must lock after the first request");
            await vm.SubmitAsync();
            SmokeAssert.Equal(1, gateway.RegisterCalls, "Submit after receipt must refresh rather than register again");
            SmokeAssert.Equal(1, gateway.GetCalls, "Submit after receipt must fetch the durable receipt");
            foreach (var identity in new[] { "asset", "batch", "digest", "expiry" })
            {
                gateway.ChangedIdentity = identity;
                await RejectAsync(() => vm.RefreshAsync());
                SmokeAssert.Equal("33333333-3333-4333-8333-333333333333", vm.Receipt!.BatchId,
                    "An untrusted refreshed identity must not replace the previously accepted receipt");
            }
            gateway.ChangedIdentity = null;
            var getsBeforeTamper = gateway.GetCalls;

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

            var restartedGateway = new RecordingGateway();
            var restarted = new ReferenceBatchPreviewViewModel(restartedGateway, stager, Continuation(), Package());
            await restarted.AddAsync("shot-1", source, "USER_SUPPLIED", null);
            restarted.UserConfirmsPreviewAndRights = true;
            await restarted.SubmitAsync();
            SmokeAssert.Equal(originalKey, restartedGateway.LastKey, "The same immutable selection must retain its key across reconstruction");

            var mismatchGateway = new RecordingGateway { MismatchReceipt = true };
            var mismatched = new ReferenceBatchPreviewViewModel(mismatchGateway, stager, Continuation(), Package());
            await mismatched.AddAsync("shot-1", source, "USER_SUPPLIED", null);
            mismatched.UserConfirmsPreviewAndRights = true;
            await RejectAsync(() => mismatched.SubmitAsync());
            SmokeAssert.True(mismatched.Receipt is null, "A mismatched receipt must never be exposed as an accepted request");

            var staged = Path.Combine(root, vm.Items[0].InputRelativePath.Replace('/', Path.DirectorySeparatorChar));
            File.SetAttributes(staged, FileAttributes.Normal);
            await File.WriteAllBytesAsync(staged, new byte[] { 1, 2, 3 });
            await RejectAsync(() => vm.RefreshAsync());
            SmokeAssert.Equal(getsBeforeTamper, gateway.GetCalls, "Changed staged bytes must prevent even receipt refresh");
            await RejectAsync(() => vm.AddAsync("text-shot", source, "USER_SUPPLIED", null));
            var bad = Package() with { QualityOutcome = "FAIL" };
            await RejectAsync(() => Task.Run(() => new ReferenceBatchPreviewViewModel(gateway, stager, Continuation(), bad)));
        }
        finally
        {
            foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(root, recursive: true);
        }
    }


    private static async Task VerifySealedV2SelectionAsync(byte[] png)
    {
        var root = Path.Combine(Path.GetTempPath(), "reference-v2-preview-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            // ── These are client-side candidates only; Mac Core validates the actual seal.
            var source = Path.Combine(root, "source.png");
            await File.WriteAllBytesAsync(source, png);
            var policy = new ReferencePreviewFilePolicy(ProductionLocalEnvironment.ResolveUnderRoot,
                ProductionLocalEnvironment.AssertNoLinkEscape, ProductionLocalEnvironment.IsOrdinaryFile,
                ProductionLocalEnvironment.Sha256FileAsync);
            var stager = new ReferencePreviewSnapshotStager(root, policy, ReferenceBatchPreviewViewModel.ValidateImageAsync);
            var gateway = new RecordingGateway { FailNextPost = true };
            var vm = new ReferenceBatchPreviewViewModel(gateway, stager, Continuation(), V2CandidatePackage());

            SmokeAssert.Equal(3, vm.EligibleShots.Length, "Sealed-v2 candidate must expose exactly three shot ids");
            SmokeAssert.Equal(3, vm.KeyframeInstructions.Count, "Display all sealed keyframe instructions");
            // 01. Frozen shot briefs must appear without opening a second JSON report.
            //     No local images, approvals or GPU tasks are implied by these cards.
            SmokeAssert.Equal(3, vm.CompositionWorkOrders.Count,
                "Existing WPF review must immediately show three frozen composition briefs");
            SmokeAssert.True(vm.CompositionWorkOrders.All(x => x.Status == "UNVERIFIED"),
                "Absent local evidence must never be presented as a missing or observed image");
            SmokeAssert.Equal("Opening pose two", vm.CompositionWorkOrders[1].StillPrompt,
                "Local work card must reuse the exact frozen Creative Kit prompt");
            SmokeAssert.Equal("kitchen-scene", vm.CompositionWorkOrders[1].SceneId,
                "Show the frozen scene identity without a second user input");
            SmokeAssert.Equal("close-up", vm.CompositionWorkOrders[1].CameraFraming,
                "Show the frozen camera framing beside the per-shot brief");
            SmokeAssert.Equal("Lock bowl", vm.CompositionWorkOrders[2].ReviewChecklist,
                "Review checklist must appear without a Qwen local report");
            SmokeAssert.Equal(0, vm.Items.Count, "Frozen briefs cannot stage images");
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Frozen briefs cannot create Core approvals");
            SmokeAssert.Equal("Opening pose two", vm.KeyframeInstructions[1].StillPrompt, "Preserve Core prompts");
            SmokeAssert.Equal("Lock bowl", vm.KeyframeInstructions[2].ReviewChecklist, "Preserve checklist");
            SmokeAssert.True(vm.EligibleShots.SequenceEqual(new[] { "shot-1", "shot-2", "shot-3" }),
                "The v2 candidate shot order/identity changed");
            // 01. 直接复用 #342 本地构图工作单，在原有 WPF 审批页展示缺失镜头。
            //     此报告既不能选择参考图，也不能发起 Owner/GPU 审批。
            var workOrder = new
            {
                schema = "picotoo.qwen-reference-readiness.v1",
                status = "BLOCKED_MISSING_REFERENCES",
                creative_package_sha256 = vm.CreativePackageDigest,
                creative_kit_digest = new string('a', 64),
                source_rights_confirmed = false,
                source_inputs_verified_for_production = false,
                production_authorized = false,
                gpu_post = 0,
                composition_work_order = new
                {
                    schema = "picotoo.qwen-local-composition-workorder.v1",
                    creative_kit_digest = new string('a', 64),
                    shot_count = 3,
                    source_workflow_modified = false,
                    all_images_approved = false,
                    gpu_post = 0,
                    items = vm.KeyframeInstructions.Select((item, index) => new
                    {
                        shot_id = item.ShotId,
                        order = index + 1,
                        composition_status = index == 0 ? "OBSERVED_UNAPPROVED" : "NEEDS_DISTINCT_COMPOSITION",
                        existing_input_filename = index == 0 ? "old-composition.png" : (string?)null,
                        source = "FROZEN_CREATIVE_KEYFRAME_KIT",
                        creative_still_prompt = item.StillPrompt,
                        camera_framing = item.CameraFraming,
                        scene_id = item.SceneId,
                        creative_still_prompt_sha256 = Convert.ToHexStringLower(
                            SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(item.StillPrompt))),
                        review_checklist = item.ReviewChecklist.Split('\n'),
                        prompt_text_local_only = true,
                        new_image_created = false,
                        owner_approved = false
                    }).ToArray()
                }
            };
            var workOrderPath = Path.Combine(root, "three-shot-workorder.json");
            await File.WriteAllTextAsync(workOrderPath, JsonSerializer.Serialize(workOrder));
            SmokeAssert.True(vm.CanLoadCompositionWorkOrder, "Frozen v2 must permit local-only work-order reading");
            await vm.LoadCompositionWorkOrderAsync(workOrderPath);
            SmokeAssert.Equal(3, vm.CompositionWorkOrders.Count, "Three shot-scoped work items were not exposed");
            SmokeAssert.Equal("OBSERVED_UNAPPROVED", vm.CompositionWorkOrders[0].Status,
                "Historical S1 must never be approved by an observation report");
            SmokeAssert.True(vm.CompositionWorkOrders.Skip(1).All(x => x.Status == "NEEDS_DISTINCT_COMPOSITION"),
                "S2/S3 must remain explicitly missing before local image creation");
            var workOrderPanel = new ReferenceBatchPreviewPanel(vm);
            workOrderPanel.Measure(new Size(1000, 700));
            workOrderPanel.Arrange(new Rect(0, 0, 1000, 700));
            workOrderPanel.UpdateLayout();
            Dispatcher.CurrentDispatcher.Invoke(() => { }, DispatcherPriority.DataBind);
            var visibleWorkOrders = (ItemsControl)workOrderPanel.FindName("CompositionWorkOrderList");
            SmokeAssert.Equal(3, visibleWorkOrders.Items.Count,
                "Existing WPF review screen must display all three frozen work orders");
            // 03. Never silently mark a Comfy-generated reference USER_SUPPLIED.
            //     The user must actively choose the origin for every manual
            //     image-staging interaction before any native file dialog opens.
            var sourceChoice = (ComboBox)workOrderPanel.FindName("SourceComboBox");
            SmokeAssert.Equal(-1, sourceChoice.SelectedIndex,
                "Source origin must have no default USER_SUPPLIED classification");
            var sourceShot = (ComboBox)workOrderPanel.FindName("ShotComboBox");
            sourceShot.SelectedItem = "shot-2";
            ((Button)workOrderPanel.FindName("ChooseReferenceButton")).RaiseEvent(
                new RoutedEventArgs(Button.ClickEvent));
            SmokeAssert.True(((TextBlock)workOrderPanel.FindName("OperationStatusText")).Text
                .Contains("来源声明", StringComparison.Ordinal),
                "Missing origin must be rejected before opening the native file picker");
            SmokeAssert.Equal(0, vm.Items.Count,
                "A missing origin must not stage an image or infer legal source");
            SmokeAssert.Equal(0, gateway.RegisterCalls,
                "A missing origin must never request Mac Core approval");
            sourceChoice.SelectedIndex = 1;
            ((Button)workOrderPanel.FindName("ChooseReferenceButton")).RaiseEvent(
                new RoutedEventArgs(Button.ClickEvent));
            SmokeAssert.True(((TextBlock)workOrderPanel.FindName("OperationStatusText")).Text
                .Contains("LICENSED", StringComparison.Ordinal),
                "Selecting LICENSED without a source digest must fail before native file selection");
            SmokeAssert.Equal(0, vm.Items.Count,
                "Missing LICENSED evidence must never stage a reference");
            sourceChoice.SelectedIndex = -1;
            // 02. A shot card uses the ORIGINAL source selector and snapshot
            //     picker, not a second auto-approval surface or API client.
            var cardTemplate = (DependencyObject)visibleWorkOrders.ItemTemplate!.LoadContent();
            SmokeAssert.Equal(1, VisualButtons(cardTemplate).Count(button =>
                button.Content is string text && text == "为此镜头选择参考图…"),
                "Each shot card must offer the existing manual local-image picker");
            SmokeAssert.Equal(0, gateway.RegisterCalls,
                "Rendering a per-shot selection button must not POST to Core");
            SmokeAssert.Equal(0, vm.Items.Count, "Reading the work order must not stage any candidate");
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Work-order read must not call Core");
            var forgedOrder = JsonNode.Parse(JsonSerializer.Serialize(workOrder))!.AsObject();
            forgedOrder["composition_work_order"]!["items"]![1]!["creative_still_prompt"] = "fabricated";
            var forgedOrderPath = Path.Combine(root, "forged-workorder.json");
            await File.WriteAllTextAsync(forgedOrderPath, forgedOrder.ToJsonString());
            await RejectAsync(() => vm.LoadCompositionWorkOrderAsync(forgedOrderPath));
            SmokeAssert.Equal(3, vm.CompositionWorkOrders.Count,
                "Forged evidence must never erase the three immutable Core-frozen briefs");
            SmokeAssert.True(vm.CompositionWorkOrders.All(x => x.Status == "UNVERIFIED"
                && x.ExistingFilename == string.Empty),
                "A rejected Qwen report must remove only untrusted observation claims");
            SmokeAssert.Equal("Opening pose two", vm.CompositionWorkOrders[1].StillPrompt,
                "Rejected report must retain only the original Creative Kit prompt");
            await vm.LoadCompositionWorkOrderAsync(workOrderPath);
            var forgedCamera = JsonNode.Parse(JsonSerializer.Serialize(workOrder))!.AsObject();
            forgedCamera["composition_work_order"]!["items"]![1]!["camera_framing"] = "invented camera";
            var forgedCameraPath = Path.Combine(root, "forged-camera.json");
            await File.WriteAllTextAsync(forgedCameraPath, forgedCamera.ToJsonString());
            await RejectAsync(() => vm.LoadCompositionWorkOrderAsync(forgedCameraPath));
            SmokeAssert.Equal(3, vm.CompositionWorkOrders.Count,
                "Camera spoofing must not erase the frozen three-shot production briefs");
            SmokeAssert.True(vm.CompositionWorkOrders.All(x => x.Status == "UNVERIFIED"),
                "Camera spoofing must discard every claim of an observed image");
            SmokeAssert.Equal("close-up", vm.CompositionWorkOrders[1].CameraFraming,
                "Camera spoofing must restore the original frozen framing");
            await vm.LoadCompositionWorkOrderAsync(workOrderPath);
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Neither accepted nor forged report may create approval");

            // 06. Different shot IDs / CAS filenames with identical bytes
            //     must not enable the SEALED V2 WPF approval request.
            //     Legacy v1 batch behavior is exercised by the older fixture.
            var duplicateGateway = new RecordingGateway();
            var duplicateV2 = new ReferenceBatchPreviewViewModel(
                duplicateGateway, stager, Continuation(), V2CandidatePackage());
            foreach (var shot in duplicateV2.EligibleShots)
                await duplicateV2.AddAsync(shot, source, "USER_SUPPLIED", null);
            SmokeAssert.Equal(3, duplicateV2.Items.Count,
                "Duplicate-byte regression must exercise complete three-shot staging");
            SmokeAssert.Equal(1, duplicateV2.Items.Select(x => x.Sha256)
                .Distinct(StringComparer.Ordinal).Count(),
                "Fixture must really contain renamed byte-identical images");
            duplicateV2.UserConfirmsPreviewAndRights = true;
            SmokeAssert.True(!duplicateV2.CanSubmit,
                "V2 cannot enable approval for identical images with three different paths");
            await RejectAsync(() => duplicateV2.SubmitAsync());
            SmokeAssert.Equal(0, duplicateGateway.RegisterCalls,
                "A direct V2 submit must fail before Core when compositions share bytes");

            // 01. 真实 UI 读取本地观察清单，但不将观察结果视为许可或审批。
            var observedRoot = Path.Combine(root, "local-comfy-output");
            Directory.CreateDirectory(observedRoot);
            var observedShots = Enumerable.Range(1, 3).Select(i =>
            {
                var shot = $"shot-{i}";
                // Distinct real PNG bytes per shot: duplicate hashes are forbidden by the collector.
                var pixels = new byte[] { 0, 0, (byte)(40 * i), 255, 0, (byte)(60 * i), 0, 255 };
                var image = BitmapSource.Create(2, 1, 96, 96, PixelFormats.Bgra32, null, pixels, 8);
                var outputEncoder = new PngBitmapEncoder();
                outputEncoder.Frames.Add(BitmapFrame.Create(image));
                using var encoded = new MemoryStream();
                outputEncoder.Save(encoded);
                var imageBytes = encoded.ToArray();
                var digest = Convert.ToHexStringLower(SHA256.HashData(imageBytes));
                File.WriteAllBytes(Path.Combine(observedRoot, shot + ".png"), imageBytes);
                return new
                {
                    shot_id = shot, order = i, prompt_id = $"00000000-0000-4000-8000-{i:000000000000}",
                    prepared_graph_sha256 = new string('c', 64),
                    selected_reference = (object?)null,
                    candidates = new[]
                    {
                        new
                        {
                            output_relative_path = shot + ".png", sha256 = digest, bytes = imageBytes.Length,
                            width = 2, height = 1, image_container_crc_verified = true,
                            pixels_decoded = false, visual_review = "UNREVIEWED",
                        }
                    }
                };
            }).ToArray();
            var observedManifest = new
            {
                schema = "picotoo.local-keyframe-output-candidates.v1",
                creative_package_id = vm.CreativePackageId,
                creative_package_sha256 = vm.CreativePackageDigest,
                keyframe_kit_digest = new string('a', 64),
                recorded_image_bytes_observed = true, candidate_files_staged = false,
                source_rights_confirmed = false, reference_approved = false,
                review_status = "NEEDS_HUMAN_REVIEW", gpu_post = 0,
                shots = observedShots
            };
            var observedFile = Path.Combine(root, "candidate_manifest.json");
            await File.WriteAllTextAsync(observedFile, JsonSerializer.Serialize(observedManifest));
            SmokeAssert.True(vm.CanLoadObservedCandidates, "Sealed three-shot view should accept read-only candidates");
            await vm.LoadObservedCandidatesAsync(observedFile);
            SmokeAssert.Equal(3, vm.ObservedCandidates.Count, "Full candidate observation lost shots");
            await vm.InspectObservedCandidatesAsync(observedRoot);
            SmokeAssert.True(vm.ObservedCandidates.All(x => x.Preview is { IsFrozen: true }),
                "Real local image thumbnails must decode for all observed stills");
            SmokeAssert.Equal(0, vm.Items.Count, "Read-only observation must never stage images");
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Thumbnail read may not create approvals");
            // 02. Any changed file must invalidate EVERY preview, not leave one trusted-looking thumbnail.
            var changedThumbnail = Path.Combine(observedRoot, "shot-2.png");
            var originalSecondImage = File.ReadAllBytes(changedThumbnail);
            File.WriteAllBytes(changedThumbnail, [1, 2, 3]);
            await RejectAsync(() => vm.InspectObservedCandidatesAsync(observedRoot));
            SmokeAssert.True(vm.ObservedCandidates.All(x => x.Preview is null),
                "One corrupt thumbnail must clear the complete untrusted observation");
            SmokeAssert.Equal(0, gateway.RegisterCalls,
                "Thumbnail corruption must never write an approval");
            File.WriteAllBytes(changedThumbnail, originalSecondImage);
            await vm.InspectObservedCandidatesAsync(observedRoot);
            SmokeAssert.True(vm.ObservedCandidates.All(x => x.Preview is { IsFrozen: true }),
                "Restoring original bytes should permit the exact same read-only preview");
            SmokeAssert.True(!vm.UserConfirmsPreviewAndRights && gateway.RegisterCalls == 0,
                "Observed output cannot grant rights or write an approval");
            await RejectAsync(() => vm.AddObservedCandidateAsync(vm.ObservedCandidates[0], observedRoot, "not-a-license"));
            SmokeAssert.Equal(0, vm.Items.Count, "Invalid license must reject observed candidate");
            await vm.AddObservedCandidateAsync(vm.ObservedCandidates[0], observedRoot, new string('e', 64));
            SmokeAssert.Equal("LICENSED", vm.Items.Single().SourceReference,
                "Generated candidate must not silently become USER_SUPPLIED");
            SmokeAssert.True(!vm.UserConfirmsPreviewAndRights && gateway.RegisterCalls == 0,
                "Explicit selection must not confirm rights or create approval");
            // 02. Changing the real file after observation must block another import.
            File.WriteAllBytes(Path.Combine(observedRoot, "shot-2.png"), [1, 2, 3]);
            await RejectAsync(() => vm.AddObservedCandidateAsync(
                vm.ObservedCandidates[1], observedRoot, new string('e', 64)));
            SmokeAssert.Equal(1, vm.Items.Count, "Tampered observed image must not replace staged image");
            File.WriteAllBytes(Path.Combine(observedRoot, "shot-2.png"), originalSecondImage);
            // 03. A forged manifest must not reuse the same image across two shots.
            var duplicateJson = JsonSerializer.Serialize(observedManifest).Replace(
                observedShots[1].candidates[0].sha256,
                observedShots[0].candidates[0].sha256, StringComparison.Ordinal);
            var duplicateFile = Path.Combine(root, "duplicate-candidate.json");
            await File.WriteAllTextAsync(duplicateFile, duplicateJson);
            await RejectAsync(() => vm.LoadObservedCandidatesAsync(duplicateFile));
            SmokeAssert.Equal(0, vm.ObservedCandidates.Count, "Duplicate source bytes must fail closed");
            // 04. Wrong package digest must fail before selecting any local file.
            var alteredJson = JsonSerializer.Serialize(observedManifest).Replace(
                vm.CreativePackageDigest, new string('f', 64), StringComparison.Ordinal);
            var alteredFile = Path.Combine(root, "wrong-candidate.json");
            await File.WriteAllTextAsync(alteredFile, alteredJson);
            await RejectAsync(() => vm.LoadObservedCandidatesAsync(alteredFile));
            SmokeAssert.Equal(0, vm.ObservedCandidates.Count, "Failed manifest must clear untrusted observations");
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Observed candidate path must not call Core");

            // 05. Comfy PNG metadata must never invent a Prompt ID or claim
            //     a successful historical job when /history has been cleared.
            var embedded = JsonNode.Parse(JsonSerializer.Serialize(observedManifest))!.AsObject();
            embedded["history_provenance"] = "PNG_EMBEDDED_NO_HISTORY";
            embedded["comfy_history_success_verified"] = false;
            foreach (var shot in embedded["shots"]!.AsArray())
            {
                shot!["prompt_id"] = null;
                foreach (var image in shot["candidates"]!.AsArray())
                    image!["embedded_prompt_graph_verified"] = true;
            }
            var embeddedPath = Path.Combine(root, "historyless-candidate.json");
            await File.WriteAllTextAsync(embeddedPath, embedded.ToJsonString());
            await vm.LoadObservedCandidatesAsync(embeddedPath);
            SmokeAssert.Equal(3, vm.ObservedCandidates.Count,
                "Exact embedded graph evidence should retain three unapproved candidates");
            SmokeAssert.True(vm.ObservedCandidates.All(x => x.PromptId.Length == 0),
                "Missing historical Prompt ID must never be fabricated");
            SmokeAssert.Equal(0, gateway.RegisterCalls, "PNG metadata may not POST an approval");
            embedded["comfy_history_success_verified"] = true;
            await File.WriteAllTextAsync(embeddedPath, embedded.ToJsonString());
            await RejectAsync(() => vm.LoadObservedCandidatesAsync(embeddedPath));
            SmokeAssert.Equal(0, vm.ObservedCandidates.Count,
                "Forged Comfy historical success must fail closed");
            embedded["comfy_history_success_verified"] = false;
            embedded["shots"]![0]!["candidates"]![0]!["embedded_prompt_graph_verified"] = false;
            await File.WriteAllTextAsync(embeddedPath, embedded.ToJsonString());
            await RejectAsync(() => vm.LoadObservedCandidatesAsync(embeddedPath));
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Unverified embedded graph may not write Core");

            await vm.AddAsync("shot-1", source, "USER_SUPPLIED", null);
            vm.UserConfirmsPreviewAndRights = true;
            SmokeAssert.True(!vm.CanSubmit, "One v2 still must not enable request submission");
            await RejectAsync(() => vm.SubmitAsync());
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Partial v2 reference must not POST to Core");

            // 06. 合法的三镜头成功测试使用之前已单独构造的不同 PNG。
            //     相同字节复用的失败路径由 duplicateV2 回归独立覆盖。
            await vm.AddAsync("shot-2", Path.Combine(observedRoot, "shot-2.png"),
                "USER_SUPPLIED", null);
            vm.UserConfirmsPreviewAndRights = true;
            SmokeAssert.True(!vm.CanSubmit, "Two v2 stills must not enable request submission");
            await RejectAsync(() => vm.SubmitAsync());
            SmokeAssert.Equal(0, gateway.RegisterCalls, "Two-shot v2 request must not POST to Core");

            await vm.AddAsync("shot-3", Path.Combine(observedRoot, "shot-3.png"),
                "USER_SUPPLIED", null);
            SmokeAssert.Equal(3, vm.Items.Select(x => x.Sha256).Distinct(StringComparer.Ordinal).Count(),
                "Full v2 fixture must use three truly distinct synthetic image byte identities");
            SmokeAssert.True(!vm.CanSubmit, "All three images still require fresh rights consent");
            vm.UserConfirmsPreviewAndRights = true;
            SmokeAssert.True(vm.CanSubmit, "All three snapshots plus explicit consent must enable submission");
            await RejectAsync(() => vm.SubmitAsync()); // Synthetic unknown network outcome only.
            SmokeAssert.Equal(1, gateway.RegisterCalls, "Complete v2 batch must make one request");
            SmokeAssert.Equal(3, gateway.Request!.SelectedReferences.Length,
                "Actual v2 request must bind exactly three staged images");
            SmokeAssert.True(!vm.CanEdit, "Ambiguous v2 POST must freeze the exact image selection");
            await RejectAsync(() => vm.AddAsync("shot-2", source, "USER_SUPPLIED", null));

            // 生产创建只能在三张快照、独立批准、显式操作之后进入 v1.1。
            await RejectAsync(() => vm.CreateReviewedPlanAsync());
            SmokeAssert.Equal(0, gateway.CreateCalls, "Unknown registration must not create a plan");
            await vm.SubmitAsync();
            SmokeAssert.True(!vm.CanCreateReviewedPlan, "Pending receipt must not create a plan");
            gateway.ReceiptStatus = "Approved";
            await vm.RefreshAsync();
            SmokeAssert.True(vm.CanCreateReviewedPlan, "Fresh full approval must enable explicit plan creation");
            SmokeAssert.Equal(0, gateway.CreateCalls, "Refresh must never create a plan");
            gateway.ReceiptStatus = "Revoked";
            await RejectAsync(() => vm.CreateReviewedPlanAsync());
            SmokeAssert.Equal(0, gateway.CreateCalls, "Revoked approval must block POST");
            gateway.ReceiptStatus = "Approved";
            await vm.RefreshAsync();
            gateway.TamperPlan = true;
            await RejectAsync(() => vm.CreateReviewedPlanAsync());
            SmokeAssert.True(vm.CreatedProductionJob is null, "Tampered plan cannot be displayed as accepted");
            var firstKey = gateway.ProductionKey;
            gateway.TamperPlan = false;
            await vm.RefreshAsync();
            await vm.CreateReviewedPlanAsync();
            SmokeAssert.Equal(firstKey, gateway.ProductionKey, "Unknown plan receipt retry must preserve key");
            SmokeAssert.True(vm.CreatedProductionJob is not null && !vm.CanCreateReviewedPlan,
                "Verified three-shot plan must be shown exactly once");

            // 04. App restart restores exact three private image snapshots from a persisted Core receipt.
            var resumed = new ReferenceBatchPreviewViewModel(gateway, stager, Continuation(), V2CandidatePackage());
            SmokeAssert.True(resumed.CanResumeReferenceBatch, "New session should permit read-only batch recovery");
            await RejectAsync(() => resumed.ResumeReferenceBatchAsync("not-a-uuid"));
            SmokeAssert.Equal(0, resumed.Items.Count, "Invalid approval ID must not stage references");
            await resumed.ResumeReferenceBatchAsync("44444444-4444-4444-8444-444444444444");
            SmokeAssert.Equal(3, resumed.Items.Count, "Restart must restore all frozen snapshot images");
            SmokeAssert.True(!resumed.CanEdit && !resumed.CanResumeReferenceBatch
                && !resumed.CanCreateReviewedPlan && !resumed.UserConfirmsPreviewAndRights,
                "Restart may not implicitly restore rights, approve or create production");
            var callsBeforeRefresh = gateway.GetCalls;
            await resumed.RefreshAsync();
            SmokeAssert.Equal(callsBeforeRefresh + 1, gateway.GetCalls,
                "Restart must re-query the existing approval status");
            SmokeAssert.True(resumed.CanCreateReviewedPlan,
                "Previously approved exact snapshot may resume explicit v1.1 plan creation");
            await resumed.CreateReviewedPlanAsync();
            SmokeAssert.Equal(firstKey, gateway.ProductionKey,
                "Restart must reuse same immutable production idempotency identity");
            SmokeAssert.Equal(gateway.RegisterCalls, 2,
                "Read-only restart must never POST another registration");

            // ── Missing v2 markers and unrelated legacy T2V stay unselectable.
            var legacy = new ReferenceBatchPreviewViewModel(
                new RecordingGateway(), stager, Continuation(), V1TextCandidatePackage());
            SmokeAssert.Equal(0, legacy.EligibleShots.Length,
                "Legacy all-T2V packages must not become image-approval candidates");
            await RejectAsync(() => legacy.AddAsync("shot-1", source, "USER_SUPPLIED", null));
            Console.WriteLine("REFERENCE_V2_THREE_SHOT_PREVIEW=PASS; PENDING_ONLY=TRUE; POST_BEFORE_FULL_CONSENT=0; GPU_POST=0");
        }
        finally
        {
            foreach (var path in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
                File.SetAttributes(path, FileAttributes.Normal);
            Directory.Delete(root, recursive: true);
        }
    }

    private static CreativePackageRecord V2CandidatePackage() => Package() with
    {
        Manifest = JsonElement.Parse("""
        {"creative_package_id":"22222222-2222-4222-8222-222222222222","creative_job_id":"job-1",
         "quality_outcome":"PASS","source_set_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
         "stage_results":{"video_bible.v1":{},"creative_brief.v1":{"output_profile_id":"video.landscape.v1"},
           "keyframe_kit.v1":{"schema_version":"keyframe_kit.v1",
             "kit_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bible_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
             "keyframes":[
               {"shot_id":"shot-1","order":1,"still_prompt":"Opening pose one","approval_status":"PENDING_HUMAN_REVIEW","review_checklist":["Lock identity"]},
               {"shot_id":"shot-2","order":2,"still_prompt":"Opening pose two","approval_status":"PENDING_HUMAN_REVIEW","scene_id":"kitchen-scene","camera_framing":"close-up","review_checklist":["Lock scene"]},
               {"shot_id":"shot-3","order":3,"still_prompt":"Opening pose three","approval_status":"PENDING_HUMAN_REVIEW","review_checklist":["Lock bowl"]}]},"script.v1":{},
           "shot_plan.v1":{"shots":[
             {"shot_id":"shot-1","render_intent":"GENERATIVE_VIDEO","duration_seconds":4},
             {"shot_id":"shot-2","render_intent":"GENERATIVE_VIDEO","duration_seconds":4},
             {"shot_id":"shot-3","render_intent":"GENERATIVE_VIDEO","duration_seconds":4}]}}}
        """),
    };

    private static CreativePackageRecord V1TextCandidatePackage() => Package() with
    {
        Manifest = JsonElement.Parse("""
        {"creative_package_id":"22222222-2222-4222-8222-222222222222","creative_job_id":"job-1",
         "quality_outcome":"PASS","source_set_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
         "stage_results":{"shot_plan.v1":{"shots":[
             {"shot_id":"shot-1","render_intent":"GENERATIVE_VIDEO"},
             {"shot_id":"shot-2","render_intent":"GENERATIVE_VIDEO"},
             {"shot_id":"shot-3","render_intent":"GENERATIVE_VIDEO"}]}}}
        """),
    };

    private static GoalVideoContinuationRecord Continuation() => new("11111111-1111-4111-8111-111111111111", new string('a', 64),
        new string('b', 64), "job-1", "22222222-2222-4222-8222-222222222222", new string('c', 64), "creative_ready", null, null);

    private static CreativePackageRecord Package() => new("22222222-2222-4222-8222-222222222222", "job-1", new string('d', 64),
        new string('c', 64), "packages/package-1.zip", JsonElement.Parse("""
        {"creative_package_id":"22222222-2222-4222-8222-222222222222","creative_job_id":"job-1","quality_outcome":"PASS",
         "source_set_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
         "stage_results":{"shot_plan.v1":{"shots":[{"shot_id":"shot-1","render_intent":"IMAGE_TO_VIDEO"},
         {"shot_id":"text-shot","render_intent":"TEXT_TO_VIDEO"}]}}}
        """), "PASS", DateTimeOffset.UtcNow);

    private sealed class RecordingGateway : IReviewedThreeShotPlanGateway
    {
        public int CreateCalls { get; private set; }
        public string ReceiptStatus { get; set; } = "Pending";
        public bool TamperPlan { get; set; }
        public string? ProductionKey { get; private set; }
        private ProductionJobRecord? _productionJob;
        public int RegisterCalls { get; private set; }
        public int GetCalls { get; private set; }
        public bool FailNextPost { get; set; }
        public bool MismatchReceipt { get; set; }
        public string? ChangedIdentity { get; set; }
        public TaskCompletionSource RegisterEntered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public string? LastKey { get; private set; }
        public ReferenceBatchRequest? Request { get; private set; }
        public TaskCompletionSource<ReferenceBatchReceipt>? Pending { get; set; }

        public Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(ReferenceBatchRequest request,
            string key, CancellationToken cancellationToken)
        {
            RegisterCalls++;
            Request = request;
            LastKey = key;
            RegisterEntered.TrySetResult();
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
        public Task<ProductionJobRecord> CreateReviewedThreeShotV11Async(ProductionJobCreateRequest request,
            string approvedReferenceId, CancellationToken cancellationToken)
        {
            CreateCalls++;
            ProductionKey = request.IdempotencyKey;
            var receipt = CreateReceipt();
            SmokeAssert.Equal(receipt.ApprovalId, approvedReferenceId, "Must use approval, not asset or batch ID");
            var now = DateTimeOffset.UtcNow;
            _productionJob = new ProductionJobRecord("88888888-8888-4888-8888-888888888888",
                request.CreativePackageId, receipt.CreativePackageDigest, "goal-" + receipt.GoalId,
                request.ProductionProfile, new string('a', 64), "Ready", null, null, null, null,
                request.IdempotencyKey, now, now, null);
            var job = _productionJob;
            var plan = BuildPlan(job, false);
            _productionJob = job with { PlanDigest = Convert.ToHexString(SHA256.HashData(
                CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))).ToLowerInvariant() };
            return Task.FromResult(_productionJob);
        }

        public Task<ProductionPlanRecord> ReadReviewedProductionPlanAsync(string jobId, CancellationToken cancellationToken)
        {
            var job = _productionJob ?? throw new InvalidOperationException("No production job");
            SmokeAssert.Equal(job.ProductionJobId, jobId, "Read exact Job");
            return Task.FromResult(BuildPlan(job, TamperPlan));
        }

        private ProductionPlanRecord BuildPlan(ProductionJobRecord job, bool tamper)
        {
            var jobId = job.ProductionJobId;
            var receipt = CreateReceipt();
            var tasks = receipt.References.Select((x, i) =>
            {
                var taskId = "task-" + i;
                var asset = new ProductionReferenceAssetV11Record("reference_asset.v1", x.AssetId,
                    receipt.GoalId, "job-1", receipt.CreativePackageId, jobId, taskId, x.ShotId,
                    receipt.CreativePackageDigest, x.InputRelativePath,
                    tamper ? new string('f', 64) : x.Sha256, x.Bytes, x.SourceReference, x.SourceDigest,
                    "wan22.i2v.production.v1", receipt.ApprovalId, receipt.ApprovalRequestDigest);
                return new ProductionTaskPlanRecord(taskId, x.ShotId, i + 1, "IMAGE_TO_VIDEO", "Executable",
                    ComfyWorkflowTemplateValidator.I2VWorkflowId, "fixture", "fixture", 1, 832, 480, 24, 97, 4000, x.InputRelativePath, asset);
            }).ToArray();
            return new ProductionPlanRecord("1.1", job.ProductionProfile, jobId,
                job.CreativePackageId, job.CreativePackageDigest, job.ProjectKey, "video.landscape.v1", 12000, tasks);
        }

        public ReferenceBatchReceipt CreateReceipt()
        {
            var request = Request ?? throw new InvalidOperationException("No request");
            var json = JsonSerializer.Serialize(new
            {
                schema_version = "reference_batch.v1", batch_id = ChangedIdentity == "batch"
                    ? "66666666-6666-4666-8666-666666666666" : "33333333-3333-4333-8333-333333333333",
                approval_id = "44444444-4444-4444-8444-444444444444",
                approval_request_digest = new string(ChangedIdentity == "digest" ? 'f' : 'e', 64), status = ReceiptStatus,
                expires_at = new DateTimeOffset(2030, 1, ChangedIdentity == "expiry" ? 2 : 1, 0, 0, 0, TimeSpan.Zero), goal_id = request.GoalId,
                creative_package_id = request.CreativePackageId, creative_package_digest = request.CreativePackageDigest,
                references = request.SelectedReferences.Select((x, i) => new { asset_id = ChangedIdentity == "asset"
                    ? "77777777-7777-4777-8777-777777777777" : $"55555555-5555-4555-8555-55555555555{i + 1}", shot_id = x.ShotId,
                    input_relative_path = x.InputRelativePath, sha256 = MismatchReceipt ? new string('f', 64) : x.Sha256, bytes = x.Bytes,
                    source_reference = x.SourceReference, source_digest = x.SourceDigest })
            });
            return JsonSerializer.Deserialize<ReferenceBatchReceipt>(json)!;
        }
    }

    // 03. Inspect a native WPF DataTemplate without invoking its file chooser.
    //     The handler itself must remain an explicit user-click action.
    private static IEnumerable<Button> VisualButtons(DependencyObject root)
    {
        if (root is Button button) yield return button;
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            foreach (var child in VisualButtons(VisualTreeHelper.GetChild(root, index)))
                yield return child;
        }
    }

    private static async Task RejectAsync(Func<Task> operation)
    {
        try { await operation(); }
        catch (Exception exception) when (exception is InvalidDataException or IOException or ArgumentException or UnauthorizedAccessException) { return; }
        throw new InvalidOperationException("Invalid image must fail closed");
    }
}
