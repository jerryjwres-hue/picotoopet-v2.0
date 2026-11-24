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
            transport.Unsupported4s = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_LOCAL_4S_MODEL_UNSUPPORTED");
            transport.Unsupported4s = false;
            transport.HistoryDuplicate = true;
            await ExpectStop(client.PreflightAsync(request, settingsPath),
                "LTX_DESKTOP_MATCHING_HISTORY_EXISTS");
            transport.HistoryDuplicate = false;

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

    private sealed class FakeLtxDesktop : HttpMessageHandler
    {
        public int Count { get; private set; }
        public int PostCount { get; private set; }
        public bool QueueBusy { get; set; }
        public bool Unsupported4s { get; set; }
        public bool HistoryDuplicate { get; set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Count++;
            if (request.Method != HttpMethod.Get)
            {
                PostCount++;
                throw new InvalidOperationException("LTX_POST_NOT_AUTHORIZED_IN_TEST");
            }
            var path = request.RequestUri?.PathAndQuery;
            string json = path switch
            {
                "/api/session" => """{"status":"connected"}""",
                "/api/generation-queue" => QueueBusy
                    ? """{"active":{"generation":{"id":"busy"}},"queued":[]}"""
                    : """{"active":null,"queued":[]}""",
                "/api/generate/models-specs" => Unsupported4s
                    ? """{"downloaded_local_models":[{"model":"ltx-2.5-fast","spec":{"supported_resolutions_durations":{"720p":{"aspect_ratios":["9:16"],"fps_to_durations":{"24":[8]}}}}}]}"""
                    : """{"downloaded_local_models":[{"model":"ltx-2.5-fast","spec":{"supported_resolutions_durations":{"720p":{"aspect_ratios":["9:16"],"fps_to_durations":{"24":[4,8]}}}}}]}""",
                "/api/generations?feature=image-to-video" => HistoryDuplicate
                    ? """[{"spec":{"params":{"prompt":"Maotai sits beside the bowl, fixed camera, one head movement","model":"ltx-2.5-fast","resolution":"720p","aspectRatio":"9:16","duration":4,"fps":24,"seed":2026112201}}}]"""
                    : "[]",
                _ => throw new InvalidOperationException("UNEXPECTED_LOCAL_GET:" + path),
            };
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            });
        }
    }
}
