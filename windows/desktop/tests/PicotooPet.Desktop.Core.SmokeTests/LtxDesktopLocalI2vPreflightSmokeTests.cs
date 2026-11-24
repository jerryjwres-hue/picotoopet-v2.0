using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>只模拟本机 LTX Desktop GET；不提交任务、不使用真实素材或 GPU。</summary>
internal static class LtxDesktopLocalI2vPreflightSmokeTests
{
    public static async Task RunAsync()
    {
        var directory = Path.Combine(Path.GetTempPath(), "p0-ltx-fixture-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            // 01. Synthetic first-frame bytes. No C8B, B1, model or private
            //     image is needed for an actual local-only API-contract test.
            var frame = Path.Combine(directory, "synthetic-frame.png");
            var bytes = Encoding.ASCII.GetBytes("synthetic-not-a-real-frame");
            await File.WriteAllBytesAsync(frame, bytes).ConfigureAwait(false);
            var digest = Convert.ToHexStringLower(SHA256.HashData(bytes));
            var settingsPath = Path.Combine(directory, "settings.json");
            await File.WriteAllTextAsync(settingsPath,
                """{"user_prefers_ltx_api_video_generations":false,"use_local_text_encoder":true,"explore_auto_enhance_prompts":false}""")
                .ConfigureAwait(false);
            var request = new LtxDesktopI2vDraft(
                "S02", new string('a', 64), "design_portrait", frame, digest,
                "Maotai sits beside the bowl, fixed camera, one head movement", 2026112201);

            var transport = new FakeLtxDesktop();
            using var http = new HttpClient(transport)
            {
                BaseAddress = LtxDesktopLocalI2vPreflightClient.FixedBaseAddress,
            };
            http.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", "synthetic-test-token");
            await using var client = new LtxDesktopLocalI2vPreflightClient(http);

            // 02. Exact vendor 4s/seeded payload is produced as a template
            //     with assetId=null; execution and local lane still unverified.
            var result = await client.PreflightAsync(request, settingsPath)
                .ConfigureAwait(false);
            SmokeAssert.Equal(digest, result.FirstFrameSha256, "Frame digest mismatch");
            SmokeAssert.True(result.BytesLocallyVerified
                && result.LocalSettingsVerified && result.ModelCapabilityVerified
                && result.QueueIdleVerified && result.DuplicateHistoryAbsent,
                "Local capabilities should pass in synthetic fixture");
            SmokeAssert.True(!result.CanSubmit && !result.OwnerApproved
                && !result.VendorAssetUploaded && !result.GenerationLaneVerified
                && result.GpuPost == 0, "Preflight cannot certify or POST a GPU job");
            var template = result.VendorSubmissionTemplate;
            var model = template["params"]!;
            SmokeAssert.Equal("ltx-2.5-fast", model["model"]!.GetValue<string>(),
                "Existing vendor model changed");
            SmokeAssert.Equal("9:16", model["aspectRatio"]!.GetValue<string>(),
                "Vendor portrait aspect changed");
            SmokeAssert.Equal("720p", model["resolution"]!.GetValue<string>(),
                "Vendor resolution changed");
            SmokeAssert.Equal(4, model["duration"]!.GetValue<int>(),
                "This adapter must use documented 4-second shot instead of legacy 8s");
            SmokeAssert.Equal(24, model["fps"]!.GetValue<int>(), "FPS mismatch");
            SmokeAssert.Equal(2026112201, model["seed"]!.GetValue<int>(), "Seed changed");
            SmokeAssert.True(template["inputs"]!["startFrame"]!["assetId"] is null,
                "Must not fabricate an uploaded startFrame.assetId");
            SmokeAssert.Equal(1, template["contract_version"]!.GetValue<int>(),
                "Vendor contract version changed");
            SmokeAssert.Equal(4, transport.Count, "Preflight must perform exactly 4 GETs");
            SmokeAssert.Equal(0, transport.PostCount, "Unexpected LTX GPU POST");

            // 03. Source horizontal StoryPack is forbidden from silently
            //     becoming a 9:16 720p LTX job, with zero HTTP calls.
            var previous = transport.Count;
            var landscape = request with { SourceOutputProfile = "p0_landscape" };
            await ExpectStop(client.PreflightAsync(landscape, settingsPath),
                "LTX_DESKTOP_DRAFT_OR_PROFILE_UNVERIFIED");
            SmokeAssert.Equal(previous, transport.Count, "Landscape request sent network calls");

            // 04. Local paid-cloud switch must fail BEFORE any remote requests.
            await File.WriteAllTextAsync(settingsPath,
                """{"user_prefers_ltx_api_video_generations":true,"use_local_text_encoder":true}""");
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_LOCAL_ONLY_NOT_VERIFIED");
            SmokeAssert.Equal(previous, transport.Count, "Paid cloud setting was not blocked");

            await File.WriteAllTextAsync(settingsPath,
                """{"user_prefers_ltx_api_video_generations":false,"use_local_text_encoder":false}""");
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_LOCAL_ONLY_NOT_VERIFIED");
            SmokeAssert.Equal(previous, transport.Count, "Cloud text encoder not blocked");

            await File.WriteAllTextAsync(settingsPath,
                """{"user_prefers_ltx_api_video_generations":false,"use_local_text_encoder":true}""");

            // 05. Wrong SHA, no 4s local model, active queue and duplicate
            //     history all fail closed. Never post or retry.
            await ExpectStop(client.PreflightAsync(
                request with { FirstFrameSha256 = new string('f', 64) }, settingsPath),
                "LTX_DESKTOP_FIRST_FRAME_SHA_MISMATCH");
            transport.QueueBusy = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath), "LTX_DESKTOP_QUEUE_BUSY");
            transport.QueueBusy = false;
            transport.MalformedQueue = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_QUEUE_SCHEMA_UNVERIFIED");
            transport.MalformedQueue = false;
            transport.Unsupported4s = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_LOCAL_4S_MODEL_UNSUPPORTED");
            transport.Unsupported4s = false;
            transport.HistoryDuplicate = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_MATCHING_HISTORY_EXISTS");
            transport.HistoryDuplicate = false;
            transport.HistoryDuplicateNested = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_MATCHING_HISTORY_EXISTS");
            transport.HistoryDuplicateNested = false;

            // 06. Misconfigured endpoint or unpaired session is denied
            //     before any request, never redirected to a provider.
            using var unsafeHttp = new HttpClient(transport)
            {
                BaseAddress = new Uri("https://api.example.com/"),
            };
            unsafeHttp.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", "synthetic-test-token");
            var denied = false;
            try { _ = new LtxDesktopLocalI2vPreflightClient(unsafeHttp); }
            catch (InvalidOperationException e) { denied = e.Message == "LTX_DESKTOP_LOOPBACK_ONLY"; }
            SmokeAssert.True(denied, "Non-loopback LTX endpoint accepted");
            denied = false;
            try { _ = LtxDesktopLocalI2vPreflightClient.Create(""); }
            catch (InvalidOperationException e) { denied = e.Message == "LTX_DESKTOP_PAIRING_REQUIRED"; }
            SmokeAssert.True(denied, "Missing pair token accepted");
            SmokeAssert.Equal(0, transport.PostCount, "Local LTX preflight performed a POST");
            Console.WriteLine("LTX_DESKTOP_LOCAL_4S_PREFLIGHT=PASS; GPU_POST=0");

            // 07. Exercise actual transport against a synthetic handler ONLY.
            //     The PNG signature fixture is not a decoded user-owned frame.
            var pngBytes = new byte[] { 137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3, 4 };
            await File.WriteAllBytesAsync(frame, pngBytes);
            var frozen = request with {
                FirstFrameSha256 = Convert.ToHexStringLower(SHA256.HashData(pngBytes)),
            };
            foreach (var mode in new[] { "success", "upload-timeout", "generation-timeout" })
            {
                var fixture = new FakeLtxDesktop { SubmissionMode = mode };
                using var local = new HttpClient(fixture)
                {
                    BaseAddress = LtxDesktopLocalI2vPreflightClient.FixedBaseAddress,
                };
                local.DefaultRequestHeaders.Authorization =
                    new AuthenticationHeaderValue("Bearer", "synthetic-only");
                await using var sender = new LtxDesktopLocalI2vPreflightClient(local);
                var journal = new ProductionSubmissionJournal(Path.Combine(directory, mode));
                using var gpu = journal.AcquireGpu();
                var job = Guid.NewGuid().ToString("D");
                var task = Guid.NewGuid().ToString("D");
                var plan = new string('b', 64);
                fixture.BeforePost = () =>
                    SmokeAssert.Equal("Submitting", journal.Read(job, task)?.Phase,
                        "Durable uncertain marker must precede ALL POSTs");

                // 08. The same signed-plan digest and GPU lock are required
                //     by the internal transport. These IDs are synthetic.
                if (mode == "success")
                {
                    var receipt = await sender.SubmitOnceTransportAsync(
                        frozen, settingsPath, journal, gpu, job, task, plan);
                    SmokeAssert.Equal(FakeLtxDesktop.GenerationId, receipt.GenerationId,
                        "Vendor generation identity lost");
                    SmokeAssert.Equal(FakeLtxDesktop.AssetId, receipt.StartFrameAssetId,
                        "Vendor uploaded asset identity lost");
                    SmokeAssert.Equal(frozen.FirstFrameSha256, receipt.FirstFrameSha256,
                        "Uploaded input digest changed");
                    SmokeAssert.Equal("Submitted", journal.Read(job, task)?.Phase,
                        "Successful response was not durably bound");
                    SmokeAssert.Equal(FakeLtxDesktop.GenerationId,
                        journal.Read(job, task)?.PromptId, "Vendor ID not journaled");
                    SmokeAssert.True(fixture.UploadedBytes!.SequenceEqual(pngBytes),
                        "Multipart uploaded bytes differ from pinned input");
                    SmokeAssert.Equal(FakeLtxDesktop.AssetId,
                        fixture.Payload!["inputs"]!["startFrame"]!["assetId"]!.GetValue<string>(),
                        "Generation must reference the uploaded image UUID");
                    SmokeAssert.Equal(4, fixture.Payload!["params"]!["duration"]!.GetValue<int>(),
                        "Generation payload must be 4 seconds");
                }
                else
                {
                    await ExpectStop(sender.SubmitOnceTransportAsync(
                        frozen, settingsPath, journal, gpu, job, task, plan),
                        "LTX_SUBMISSION_TRANSPORT_UNCERTAIN");
                    SmokeAssert.Equal("Submitting", journal.Read(job, task)?.Phase,
                        "Uncertain network response must leave durable marker");
                }
                SmokeAssert.Equal(1, fixture.UploadCount, "Upload must occur once");
                SmokeAssert.Equal(mode == "upload-timeout" ? 0 : 1, fixture.GenerationCount,
                    "At most one generation POST");

                // 09. Simulate reopening the journal after a lost response;
                //     neither the same job nor another job can blindly retry.
                var posts = fixture.PostCount;
                await ExpectStop(sender.SubmitOnceTransportAsync(
                    frozen, settingsPath, journal, gpu, job, task, plan),
                    "LTX_SUBMISSION_RECONCILIATION_REQUIRED");
                await ExpectStop(sender.SubmitOnceTransportAsync(
                    frozen, settingsPath, journal, gpu, Guid.NewGuid().ToString("D"), task, plan),
                    "LTX_SUBMISSION_RECONCILIATION_REQUIRED");
                SmokeAssert.Equal(posts, fixture.PostCount, "Duplicate vendor POST occurred");
                // 10. Reopen durable journal; the legacy reconciler must not
                //     query Comfy or Core for an LTX generation, even after a crash.
                var reopened = new ProductionSubmissionJournal(Path.Combine(directory, mode));
                var persisted = reopened.Read(job, task)!;
                SmokeAssert.True(persisted.IsLtx, "Renderer tag lost during journal reload");
                SmokeAssert.Equal(mode == "upload-timeout" ? null : FakeLtxDesktop.AssetId,
                    persisted.VendorStartFrameAssetId, "Upload identity not durable");
                var legacy = new RejectLegacyReconciler();
                await ExpectStop(ProductionPendingRecovery.ReconcileTerminalAsync(
                    reopened, legacy, persisted), "MEDIA_LTX_RECOVERY_REQUIRED");
                gpu.Dispose();
                var recovery = new ProductionPendingRecovery(reopened, legacy,
                    (_, _) => throw new InvalidOperationException("LEGACY_CORE_QUERY_FOR_LTX"));
                var blocked = await recovery.ReconcileAsync();
                SmokeAssert.True(blocked.HasPending && blocked.RecoverableJobId is null,
                    "Pending LTX record must block legacy scheduling");
                SmokeAssert.True(reopened.Read(job, task)!.Phase != "Settled",
                    "Legacy recovery settled LTX without vendor evidence");
            }
            // 11. Exercise the actual signed-source journal transition with
            //     synthetic Core rechecks; no real vendor or GPU is contacted.
            var coreDraft = frozen with { ShotId = "shot-a", SourceStoryPackSha256 = "",
                SourceOutputProfile = "video.vertical.v1", SourceCreativePackageDigest = new string('c', 64) };
            foreach (var stop in new[] { 0, 1, 2 })
            {
                var fixture = new FakeLtxDesktop { SubmissionMode = "success" };
                using var local = new HttpClient(fixture) { BaseAddress = LtxDesktopLocalI2vPreflightClient.FixedBaseAddress };
                local.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", "synthetic-only");
                await using var sender = new LtxDesktopLocalI2vPreflightClient(local);
                var journal = new ProductionSubmissionJournal(Path.Combine(directory, "claimed-" + stop));
                using var gpu = journal.AcquireGpu();
                var job = Guid.NewGuid().ToString("D");
                var task = Guid.NewGuid().ToString("D");
                var plan = new string('b', 64);
                var ready = await sender.PreflightAsync(coreDraft, settingsPath);
                var intent = LtxDesktopLocalI2vPreflightClient.SubmissionIntentDigest(coreDraft, ready.VendorSubmissionTemplate);
                journal.Save(new(job, task, plan, intent, "Claimed", null, Renderer: ProductionSubmission.LtxRenderer));
                var checks = 0;
                Task Recheck(CancellationToken ct)
                {
                    ct.ThrowIfCancellationRequested();
                    if (++checks == stop) throw new InvalidOperationException("SYNTHETIC_LEASE_REVOKED");
                    return Task.CompletedTask;
                }
                if (stop == 0)
                {
                    var receipt = await sender.SubmitClaimedOnceTransportAsync(coreDraft, settingsPath,
                        journal, gpu, job, task, plan, intent, Recheck);
                    SmokeAssert.Equal(intent, receipt.JournalDigest, "Core intent changed");
                    SmokeAssert.Equal(2, checks, "Both POSTs require live lease");
                    SmokeAssert.Equal("Submitted", journal.Read(job, task)?.Phase, "Signed submission not bound");
                }
                else
                {
                    await ExpectStop(sender.SubmitClaimedOnceTransportAsync(coreDraft, settingsPath,
                        journal, gpu, job, task, plan, intent, Recheck), "SYNTHETIC_LEASE_REVOKED");
                    SmokeAssert.Equal(stop == 1 ? "Claimed" : "Submitting", journal.Read(job, task)?.Phase,
                        "Revocation changed reservation incorrectly");
                }
                SmokeAssert.Equal(stop == 1 ? 0 : 1, fixture.UploadCount, "Upload after lease denial");
                SmokeAssert.Equal(stop == 0 ? 1 : 0, fixture.GenerationCount, "Generation after lease denial");
            }
            Console.WriteLine("LTX_SYNTHETIC_ONE_SHOT_TRANSPORT=PASS; REAL_GPU_POST=0");
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    private static async Task ExpectStop(Task work, string expected)
    {
        var stopped = false;
        try { await work.ConfigureAwait(false); }
        catch (Exception e) { stopped = e.Message == expected; }
        SmokeAssert.True(stopped, "Missing fail-closed reason " + expected);
    }

    private sealed class RejectLegacyReconciler : IComfyPromptReconciler
    {
        public Task<string?> FindExactAsync(string digest, CancellationToken ct) =>
            throw new InvalidOperationException("COMFY_QUERY_FOR_LTX");
        public Task<bool> IsFinishedAsync(string promptId, CancellationToken ct) =>
            throw new InvalidOperationException("COMFY_QUERY_FOR_LTX");
    }

    private sealed class FakeLtxDesktop : HttpMessageHandler
    {
        public int Count { get; private set; }
        public int PostCount { get; private set; }
        public bool QueueBusy { get; set; }
        public bool MalformedQueue { get; set; }
        public bool Unsupported4s { get; set; }
        public bool HistoryDuplicate { get; set; }
        public bool HistoryDuplicateNested { get; set; }
        public const string AssetId = "00000000-0000-4000-8000-000000000021";
        public const string GenerationId = "00000000-0000-4000-8000-000000000022";
        public string? SubmissionMode { get; init; }
        public Action? BeforePost { get; set; }
        public int UploadCount { get; private set; }
        public int GenerationCount { get; private set; }
        public byte[]? UploadedBytes { get; private set; }
        public JsonObject? Payload { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Count++;
            if (request.Method != HttpMethod.Get)
            {
                PostCount++;
                if (SubmissionMode is null || request.Method != HttpMethod.Post
                    || request.RequestUri?.Host != "127.0.0.1" || request.RequestUri.Port != 41955)
                    throw new InvalidOperationException("LTX_POST_NOT_AUTHORIZED_IN_TEST");
                BeforePost?.Invoke();
                string response;
                if (request.RequestUri.AbsolutePath == "/api/assets/upload")
                {
                    UploadCount++;
                    if (SubmissionMode == "upload-timeout")
                        throw new HttpRequestException("synthetic lost upload response");
                    var multipart = request.Content as MultipartFormDataContent
                        ?? throw new InvalidOperationException("EXPECTED_MULTIPART");
                    var part = multipart.Single();
                    SmokeAssert.Equal("file", part.Headers.ContentDisposition?.Name?.Trim('"'),
                        "Vendor requires multipart field file");
                    UploadedBytes = await part.ReadAsByteArrayAsync(cancellationToken);
                    response = "{\"id\":\"" + AssetId + "\",\"media_kind\":\"image\"}";
                }
                else if (request.RequestUri.AbsolutePath == "/api/generations/image-to-video")
                {
                    GenerationCount++;
                    Payload = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject();
                    if (SubmissionMode == "generation-timeout")
                        throw new HttpRequestException("synthetic lost generation response");
                    response = "{\"id\":\"" + GenerationId + "\",\"status\":\"queued\"}";
                }
                else throw new InvalidOperationException("UNEXPECTED_POST");
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(response, Encoding.UTF8, "application/json"),
                };
            }
            var path = request.RequestUri?.PathAndQuery;
            string json = path switch
            {
                "/api/session" => """{"status":"connected"}""",
                "/api/generation-queue" => MalformedQueue
                    ? """{"active":null}"""
                    : QueueBusy
                        ? """{"active":{"generation":{"id":"busy"}},"queued":[]}"""
                        : """{"active":null,"queued":[]}""",
                "/api/generate/models-specs" => Unsupported4s
                    ? """{"downloaded_local_models":[{"model":"ltx-2.5-fast","spec":{"supported_resolutions_durations":{"720p":{"aspect_ratios":["9:16"],"fps_to_durations":{"24":[8]}}}}}]}"""
                    : """{"downloaded_local_models":[{"model":"ltx-2.5-fast","spec":{"supported_resolutions_durations":{"720p":{"aspect_ratios":["9:16"],"fps_to_durations":{"24":[4,8]}}}}}]}""",
                "/api/generations?feature=image-to-video" => HistoryDuplicateNested
                    ? """[[{"spec":{"params":{"prompt":"Maotai sits beside the bowl, fixed camera, one head movement","model":"ltx-2.5-fast","resolution":"720p","aspectRatio":"9:16","duration":4,"fps":24,"seed":2026112201}}}]]"""
                    : HistoryDuplicate
                        ? """[{"spec":{"params":{"prompt":"Maotai sits beside the bowl, fixed camera, one head movement","model":"ltx-2.5-fast","resolution":"720p","aspectRatio":"9:16","duration":4,"fps":24,"seed":2026112201}}}]"""
                        : "[]",
                _ => throw new InvalidOperationException("UNEXPECTED_LOCAL_GET:" + path),
            };
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
        }
    }
}
