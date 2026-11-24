using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>假 LTX REST GET 的结果核验，严格区分“vendor success”和 Core Commit。</summary>
internal static class LtxDesktopLocalI2vResultSmokeTests
{
    private const string GenerationId = "00000000-0000-4000-8000-000000000001";
    private const string FrameAssetId = "00000000-0000-4000-8000-000000000002";
    private const string VideoAssetId = "00000000-0000-4000-8000-000000000003";
    private const string Prompt = "Synthetic animation dog beside bowl, locked camera, one movement";
    private const string SignedVideoPath = "/api/assets/" + VideoAssetId + "/bytes?signature=test-only";

    public static async Task RunAsync()
    {
        // 01. Fake handler owns one authorized local result; requests must
        //     remain GET to 41955 and never contain token in output artifacts.
        var handler = new FakeResultServer();
        using var http = new HttpClient(handler)
        {
            BaseAddress = LtxDesktopLocalI2vPreflightClient.FixedBaseAddress,
        };
        http.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", "ci-local-token");
        await using var client = new LtxDesktopLocalI2vPreflightClient(http);

        var expect = new LtxDesktopGenerationExpectation(
            GenerationId, FrameAssetId, Prompt, 2026112201);
        var receipt = await client.InspectCompletedGenerationAsync(expect).ConfigureAwait(false);
        SmokeAssert.Equal(GenerationId, receipt.GenerationId, "LTX id changed");
        SmokeAssert.Equal(VideoAssetId, receipt.VideoAssetId, "LTX video asset changed");
        SmokeAssert.Equal("video/mp4", receipt.MediaType, "LTX media type changed");
        SmokeAssert.Equal("local", receipt.Lane, "LTX lane must be explicit");
        SmokeAssert.Equal(4, receipt.DurationSeconds, "LTX duration changed");
        SmokeAssert.Equal(24, receipt.Fps, "LTX fps changed");
        SmokeAssert.Equal(2026112201, receipt.Seed, "LTX seed changed");
        SmokeAssert.True(receipt.ResultIsLocal, "Local vendor lane was not checked");
        SmokeAssert.True(!receipt.SubmissionReceiptIndependentlyBoundToCore
            && !receipt.StartFrameBytesIndependentlyVerified
            && !receipt.MediaBytesDownloaded
            && !receipt.MediaGeometryVerified
            && !receipt.CanCommitProductionResult
            && receipt.GpuPost == 0,
            "Vendor succeeded must not be reported as a formally approved Core result");
        SmokeAssert.Equal(1, handler.GetCount, "One result requires one GET");
        SmokeAssert.Equal(0, handler.PostCount, "Readback cannot POST");
        SmokeAssert.Equal("/api/generations/" + GenerationId, handler.LastPath,
            "Generation ID must identify exact single vendor record");
        SmokeAssert.Equal("Bearer ci-local-token", handler.Authorization,
            "Existing DPAPI paired session must be used for GET");
        SmokeAssert.True(!receipt.ToString()!.Contains("signature=", StringComparison.Ordinal),
            "Signed download tokens must never appear in a diagnostic result");

        // 02. The historical S1/S2 records have no lane. An empty, cloud,
        //     changed or missing lane must stop rather than infer local GPU.
        await CheckBadAsync("lane_missing", "LTX_GENERATION_LOCAL_LANE_UNVERIFIED",
            root => root.Remove("lane"), client, handler, expect);
        await CheckBadAsync("lane_cloud", "LTX_GENERATION_LOCAL_LANE_UNVERIFIED",
            root => root["lane"] = "cloud", client, handler, expect);
        await CheckBadAsync("not_done", "LTX_GENERATION_NOT_SUCCEEDED",
            root => root["status"] = "queued", client, handler, expect);
        await CheckBadAsync("wrong_id", "LTX_GENERATION_ID_CONFLICT",
            root => root["id"] = "00000000-0000-4000-8000-000000000099",
            client, handler, expect);

        // 03. No output may be certified with the wrong source frame,
        //     different prompt, seed, duration, model or contract.
        await CheckBadAsync("changed_start_frame", "LTX_GENERATION_START_FRAME_ASSET_CONFLICT",
            root => ((JsonObject)root["spec"]!["inputs"]!["startFrame"]!)["assetId"] =
                "00000000-0000-4000-8000-000000000099",
            client, handler, expect);
        await CheckBadAsync("changed_prompt", "LTX_GENERATION_FROZEN_PARAMETERS_CONFLICT",
            root => ((JsonObject)root["spec"]!["params"]!)["prompt"] = "different",
            client, handler, expect);
        await CheckBadAsync("changed_seed", "LTX_GENERATION_FROZEN_PARAMETERS_CONFLICT",
            root => ((JsonObject)root["spec"]!["params"]!)["seed"] = 9,
            client, handler, expect);
        await CheckBadAsync("changed_duration", "LTX_GENERATION_FROZEN_PARAMETERS_CONFLICT",
            root => ((JsonObject)root["spec"]!["params"]!)["duration"] = 8,
            client, handler, expect);
        await CheckBadAsync("changed_model", "LTX_GENERATION_FROZEN_PARAMETERS_CONFLICT",
            root => ((JsonObject)root["spec"]!["params"]!)["model"] = "paid-cloud",
            client, handler, expect);

        // 04. One exact video and a relative signed local asset URL only:
        //     arbitrary external URLs, ambiguous videos and missing media
        //     are never offered for export or acceptance.
        await CheckBadAsync("remote_signed_url", "LTX_GENERATION_SIGNED_VIDEO_REF_INVALID",
            root => ((JsonObject)root["outputs"]![0]!)["bytes_url"] =
                "https://external.example/video.mp4?signature=secret",
            client, handler, expect);
        await CheckBadAsync("wrong_asset_signed_url", "LTX_GENERATION_SIGNED_VIDEO_REF_INVALID",
            root => ((JsonObject)root["outputs"]![0]!)["bytes_url"] =
                "/api/assets/00000000-0000-4000-8000-000000000099/bytes?signature=foreign",
            client, handler, expect);
        await CheckBadAsync("signed_url_fragment", "LTX_GENERATION_SIGNED_VIDEO_REF_INVALID",
            root => ((JsonObject)root["outputs"]![0]!)["bytes_url"] =
                SignedVideoPath + "#extra",
            client, handler, expect);
        await CheckBadAsync("changed_mime", "LTX_GENERATION_SIGNED_VIDEO_REF_INVALID",
            root => ((JsonObject)root["outputs"]![0]!)["mime_type"] =
                "application/x-msdownload",
            client, handler, expect);
        await CheckBadAsync("duplicate_video", "LTX_GENERATION_VIDEO_OUTPUT_AMBIGUOUS",
            root => ((JsonArray)root["outputs"]!).Add(
                ((JsonArray)root["outputs"]!)[0]!.DeepClone()),
            client, handler, expect);
        await CheckBadAsync("missing_video", "LTX_GENERATION_VIDEO_OUTPUT_AMBIGUOUS",
            root => root["outputs"] = new JsonArray(),
            client, handler, expect);

        // 05. Invalid generation / asset identifiers are rejected BEFORE
        //     any GET; no URL injection can escape the configured loopback.
        var oldCount = handler.GetCount;
        await ExpectFailureAsync(
            client.InspectCompletedGenerationAsync(expect with
            {
                GenerationId = "abc/../../../internet",
            }),
            "LTX_GENERATION_EXPECTATION_INVALID");
        SmokeAssert.Equal(oldCount, handler.GetCount, "Unsafe ID caused HTTP request");
        SmokeAssert.Equal(0, handler.PostCount, "No POST allowed during result readback");
        // 06. Export existing bytes without GPU. A valid container signature
        //     alone does not prove video geometry or actual decoded frames.
        var directory = Path.Combine(Path.GetTempPath(), "p0-ltx-export-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var export = await client.ExportCompletedCandidateAsync(expect, directory);
            var target = Path.Combine(directory, export.LocalFileName);
            SmokeAssert.True(File.ReadAllBytes(target).SequenceEqual(handler.Media),
                "Downloaded candidate bytes changed");
            SmokeAssert.Equal(Convert.ToHexStringLower(
                System.Security.Cryptography.SHA256.HashData(handler.Media)), export.Sha256,
                "Export receipt must hash actual downloaded bytes");
            SmokeAssert.Equal((long)handler.Media.Length, export.Bytes, "Export byte count mismatch");
            SmokeAssert.True(export.Inspection.MediaBytesDownloaded
                && !export.Inspection.MediaGeometryVerified
                && !export.Inspection.CanCommitProductionResult,
                "Downloading bytes is not final production acceptance");

            var downloads = handler.DownloadCount;
            await ExpectFailureAsync(client.ExportCompletedCandidateAsync(expect, directory),
                "LTX_EXPORT_ALREADY_EXISTS");
            SmokeAssert.Equal(downloads, handler.DownloadCount, "Existing output fetched again");
            File.Delete(target);

            handler.Media = Encoding.ASCII.GetBytes("not-a-valid-video");
            await ExpectFailureAsync(client.ExportCompletedCandidateAsync(expect, directory),
                "LTX_EXPORT_CONTAINER_SIGNATURE_INVALID");
            SmokeAssert.Equal(0, Directory.GetFiles(directory).Length,
                "Invalid response left candidate or temporary file");

            handler.Media = FakeResultServer.MakeMedia();
            handler.MediaMime = "text/html";
            await ExpectFailureAsync(client.ExportCompletedCandidateAsync(expect, directory),
                "LTX_EXPORT_MEDIA_RESPONSE_INVALID");
            handler.MediaMime = "video/mp4";
            handler.DeclaredLength = handler.Media.Length + 1;
            await ExpectFailureAsync(client.ExportCompletedCandidateAsync(expect, directory),
                "LTX_EXPORT_MEDIA_INCOMPLETE");
            handler.DeclaredLength = null;
            SmokeAssert.Equal(0, Directory.GetFiles(directory).Length,
                "Truncated or wrong MIME response left a file");
            SmokeAssert.Equal(0, handler.PostCount, "Export may not submit a new generation");
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }

        Console.WriteLine("LTX_GENERATION_LANE_LOCAL=VERIFIED_FIXTURE_ONLY; COMMIT=BLOCKED; GPU_POST=0");
    }

    private static async Task CheckBadAsync(
        string caseName, string code, Action<JsonObject> mutate,
        LtxDesktopLocalI2vPreflightClient client, FakeResultServer handler,
        LtxDesktopGenerationExpectation expected)
    {
        handler.Mutate = mutate;
        await ExpectFailureAsync(
            client.InspectCompletedGenerationAsync(expected), code);
        handler.Mutate = null;
        SmokeAssert.Equal(0, handler.PostCount, "Unexpected POST in " + caseName);
    }

    private static async Task ExpectFailureAsync(Task task, string expectedCode)
    {
        // 06. Only a strict, expected stop reason counts; test must fail
        //     if the verifier incorrectly returns an accepted record.
        var stopped = false;
        try
        {
            await task.ConfigureAwait(false);
        }
        catch (Exception error)
        {
            stopped = error.Message == expectedCode;
        }
        SmokeAssert.True(stopped, "Fail-closed check missing: " + expectedCode);
    }

    private sealed class FakeResultServer : HttpMessageHandler
    {
        public Action<JsonObject>? Mutate { get; set; }
        public int GetCount { get; private set; }
        public int PostCount { get; private set; }
        public string? LastPath { get; private set; }
        public string? Authorization { get; private set; }
        public int DownloadCount { get; private set; }
        public byte[] Media { get; set; } = MakeMedia();
        public string MediaMime { get; set; } = "video/mp4";
        public long? DeclaredLength { get; set; }

        // Synthetic header only: never claim this fixture is a playable MP4.
        public static byte[] MakeMedia() => new byte[]
        {
            0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109,
            0, 0, 0, 0, 105, 115, 111, 109, 109, 112, 52, 50,
        };

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method != HttpMethod.Get)
            {
                PostCount++;
                throw new InvalidOperationException("LTX_RESULT_READBACK_MUST_NOT_POST");
            }
            if (request.RequestUri?.PathAndQuery == SignedVideoPath)
            {
                DownloadCount++;
                if (request.RequestUri.Host != "127.0.0.1" || request.RequestUri.Port != 41955)
                    throw new InvalidOperationException("MEDIA_GET_NOT_LOOPBACK");
                var body = new ByteArrayContent(Media);
                body.Headers.ContentType = new MediaTypeHeaderValue(MediaMime);
                if (DeclaredLength.HasValue) body.Headers.ContentLength = DeclaredLength;
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = body });
            }
            GetCount++;
            LastPath = request.RequestUri?.AbsolutePath;
            Authorization = request.Headers.Authorization?.ToString();
            if (LastPath != "/api/generations/" + GenerationId
                || request.RequestUri?.Host != "127.0.0.1"
                || request.RequestUri?.Port != 41955)
            {
                throw new InvalidOperationException("UNEXPECTED_LTX_VENDOR_GET");
            }
            var root = JsonNode.Parse($$"""
              {
                "id": "{{GenerationId}}",
                "status": "succeeded",
                "lane": "local",
                "spec": {
                  "params": {
                    "prompt": "{{Prompt}}",
                    "model": "ltx-2.5-fast",
                    "resolution": "720p",
                    "aspectRatio": "9:16",
                    "duration": 4,
                    "fps": 24,
                    "seed": 2026112201,
                    "cameraMotion": "none",
                    "negativePrompt": "",
                    "promptProvenance": "typed"
                  },
                  "inputs": {
                    "startFrame": {
                      "assetId": "{{FrameAssetId}}"
                    }
                  }
                },
                "outputs": [{
                  "id": "{{VideoAssetId}}",
                  "media_kind": "video",
                  "mime_type": "video/mp4",
                  "bytes_url": "{{SignedVideoPath}}"
                }]
              }
              """)!.AsObject();
            Mutate?.Invoke(root);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    root.ToJsonString(), Encoding.UTF8, "application/json"),
            });
        }
    }
}
