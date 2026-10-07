using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class NarrationClientSmokeTests
{
    private const string SecretText = "never-log-this-narration";

    public static async Task RunAsync()
    {
        await ReadsStrictAuthenticatedPlanAsync().ConfigureAwait(false);
        await RejectsOversizedResponseAsync().ConfigureAwait(false);
        await RejectsExtraFieldsAsync().ConfigureAwait(false);
        await RedactsFailedApiBodyAsync().ConfigureAwait(false);
    }

    private static async Task ReadsStrictAuthenticatedPlanAsync()
    {
        var handler = new NarrationHandler(ValidResponse);
        using var http = new HttpClient(handler)
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "fixture-token");

        var response = await client.GetNarrationPlanAsync(
            "job/with space",
            CancellationToken.None).ConfigureAwait(false);

        SmokeAssert.Equal(
            "/api/v1/postproduction/production/job%2Fwith%20space/narration-plan",
            handler.Path,
            "Narration plan path did not escape the production job id as one segment");
        SmokeAssert.Equal(
            "Bearer fixture-token",
            handler.Authorization,
            "Narration plan request did not use paired bearer authentication");
        SmokeAssert.True(
            !string.IsNullOrWhiteSpace(handler.TraceId),
            "Narration plan request did not carry a bounded trace id");
        SmokeAssert.Equal(
            "narration.local.windows.v1",
            response.Plan.TtsProfileId,
            "Narration plan logical TTS profile was not parsed");
        SmokeAssert.Equal(2, response.Plan.Segments.Length, "Narration segments were not parsed");
    }

    private static async Task RejectsOversizedResponseAsync()
    {
        using var http = new HttpClient(new NarrationHandler(null, 256 * 1024 + 1))
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        try
        {
            _ = await client.GetNarrationPlanAsync("job-1", CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException("Oversized narration response was accepted");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "RESPONSE_TOO_LARGE",
                exception.Code,
                "Oversized narration response did not use the bounded response code");
        }
    }

    private static async Task RejectsExtraFieldsAsync()
    {
        var withExtra = ValidResponse.Replace(
            "\"schema_version\":\"1.0\"",
            "\"schema_version\":\"1.0\",\"voice_id\":\"caller-controlled\"",
            StringComparison.Ordinal);
        using var http = new HttpClient(new NarrationHandler(withExtra))
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        try
        {
            _ = await client.GetNarrationPlanAsync("job-1", CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException("Narration plan accepted caller voice authority");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "NARRATION_PLAN_INVALID",
                exception.Code,
                "Extra narration fields were not rejected as an invalid plan");
        }
    }

    private static async Task RedactsFailedApiBodyAsync()
    {
        using var http = new HttpClient(new NarrationHandler(
            $"{{\"error\":{{\"code\":\"BAD\",\"message\":\"{SecretText}\"}}}}",
            statusCode: HttpStatusCode.BadRequest))
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(http, "fixture-token");
        try
        {
            _ = await client.GetNarrationPlanAsync("job-1", CancellationToken.None)
                .ConfigureAwait(false);
            throw new InvalidOperationException("Failed narration API call did not throw");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "NARRATION_HTTP_ERROR",
                exception.Code,
                "Narration API failure was not converted to a bounded code");
            SmokeAssert.True(
                !exception.ToString().Contains(SecretText, StringComparison.Ordinal),
                "Narration text leaked through the typed API failure");
        }
    }

    private sealed class NarrationHandler(
        string? payload,
        int oversizedBytes = 0,
        HttpStatusCode statusCode = HttpStatusCode.OK) : HttpMessageHandler
    {
        public string? Path { get; private set; }
        public string? Authorization { get; private set; }
        public string? TraceId { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Path = request.RequestUri?.AbsolutePath;
            Authorization = request.Headers.Authorization?.ToString();
            TraceId = request.Headers.TryGetValues("X-Picotoo-Trace-Id", out var values)
                ? values.Single()
                : null;
            HttpContent content = oversizedBytes > 0
                ? new UnknownLengthContent(oversizedBytes)
                : new StringContent(payload!, Encoding.UTF8, "application/json");
            return Task.FromResult(new HttpResponseMessage(statusCode) { Content = content });
        }
    }

    private sealed class UnknownLengthContent(int sizeBytes) : HttpContent
    {
        protected override async Task SerializeToStreamAsync(
            Stream stream,
            TransportContext? context)
        {
            var block = new byte[4096];
            var remaining = sizeBytes;
            while (remaining > 0)
            {
                var count = Math.Min(block.Length, remaining);
                await stream.WriteAsync(block.AsMemory(0, count)).ConfigureAwait(false);
                remaining -= count;
            }
        }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }
    }

    private const string ValidResponse = """
        {
          "plan": {
            "schema_version":"1.0",
            "production_job_id":"job-1",
            "creative_package_id":"creative-1",
            "creative_package_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "production_plan_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "target_runtime_ms":3000,
            "tts_profile_id":"narration.local.windows.v1",
            "voice_profile_id":"voice.windows.default.v1",
            "narration_required":true,
            "segments":[
              {"segment_id":"segment-001","beat_id":"beat-1","order":1,"text":"Hello.","text_sha256":"2d8bd7d9bb5f85ba643f0110d50cb506a1fe439e769a22503193ea6046bb87f7","start_ms":0,"end_ms":1500},
              {"segment_id":"segment-002","beat_id":"beat-2","order":2,"text":"World.","text_sha256":"52b66d1951f731ecbecf14051c45b98498bfa189833e99dbab4aba1de4b9152e","start_ms":1500,"end_ms":3000}
            ]
          },
          "narration_plan_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        }
        """;
}
