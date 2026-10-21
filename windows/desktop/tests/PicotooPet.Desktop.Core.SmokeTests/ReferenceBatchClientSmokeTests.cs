using System.Net;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class ReferenceBatchClientSmokeTests
{
    private const string Goal = "11111111-1111-4111-8111-111111111111";
    private const string Package = "22222222-2222-4222-8222-222222222222";
    private const string Approval = "33333333-3333-4333-8333-333333333333";
    private const string Batch = "44444444-4444-4444-8444-444444444444";
    private const string Asset = "55555555-5555-4555-8555-555555555555";
    private static readonly string A = new('a', 64);
    private static readonly string B = new('b', 64);

    public static async Task RunAsync()
    {
        await SendsExactAuthenticatedRegistrationAndReadsAsync();
        ValidatesRequestBoundsAndScope();
        BindsEveryReceiptField();
        DerivesStableRequestKey();
        await RejectsMismatchedServerReceiptAsync();
        await RejectsInvalidGetAndOversizedReceiptAsync();
        await LostResponseRetryUsesOneRegistrationAsync();
    }

    private static ReferenceBatchRequest Request() => new(
        "reference_batch.v1", Goal, Package, A,
        [new("shot-1", "PicotooPet/references/a.png", A, 123, "USER_SUPPLIED", B, "wan22.i2v.production.v1")],
        true);

    private static ReferenceBatchReceipt Receipt() => new(
        "reference_batch.v1", Batch, Approval, B, "Pending",
        DateTimeOffset.Parse("2099-01-01T00:00:00Z"), Package, A, Goal,
        [new(Asset, "shot-1", "PicotooPet/references/a.png", A, 123, "USER_SUPPLIED", B)]);

    private static async Task SendsExactAuthenticatedRegistrationAndReadsAsync()
    {
        using var handler = new BatchHandler();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://core.invalid/") };
        await using var client = new MacCoreClient(http, "paired-reference-token");
        var receipt = await client.RegisterReferenceBatchAsync(Request(), "reference-key-1", CancellationToken.None);
        SmokeAssert.Equal("Pending", receipt.Status, "Registration must preserve pending authority");
        SmokeAssert.Equal(Approval, receipt.ApprovalId, "Approval identity was lost");
        var observed = await client.GetReferenceBatchAsync(Approval, CancellationToken.None);
        SmokeAssert.Equal(Asset, observed.References.Single().AssetId, "GET lost registered asset");
        SmokeAssert.Equal(2, handler.Calls.Count, "Registration or observation issued an extra authority command");
        SmokeAssert.Equal("POST /api/v1/production/references/batches", handler.Calls[0], "Wrong reference registration route");
        SmokeAssert.Equal("GET /api/v1/production/references/batches/" + Approval, handler.Calls[1], "Wrong observation route");
        SmokeAssert.Equal("Bearer paired-reference-token", handler.Authorization, "Paired authentication missing");
        SmokeAssert.True(handler.TracePresent, "Reference request missing trace header");
        SmokeAssert.Equal("reference-key-1", handler.Keys.Single(), "Exact idempotency key missing");
        using var body = JsonDocument.Parse(handler.Bodies.Single());
        const string expected = """
            {"schema_version":"reference_batch.v1","goal_id":"11111111-1111-4111-8111-111111111111","creative_package_id":"22222222-2222-4222-8222-222222222222","creative_package_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","selected_references":[{"shot_id":"shot-1","input_relative_path":"PicotooPet/references/a.png","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bytes":123,"source_reference":"USER_SUPPLIED","source_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","rights_scope":"wan22.i2v.production.v1"}],"user_confirms_preview_and_rights":true,"expires_seconds":1800}
            """;
        using var expectedBody = JsonDocument.Parse(expected);
        SmokeAssert.True(JsonElement.DeepEquals(expectedBody.RootElement, body.RootElement),
            "Reference payload changed exact preview and rights binding");
    }

    private static void ValidatesRequestBoundsAndScope()
    {
        var request = Request();
        ReferenceBatchValidation.ValidateRequest(request);
        var candidate = request.SelectedReferences[0];
        var twelve = Enumerable.Range(1, 12).Select(i => candidate with
            { ShotId = "shot-" + i, InputRelativePath = "PicotooPet/references/" + i + ".webp" }).ToArray();
        ReferenceBatchValidation.ValidateRequest(request with { SelectedReferences = twelve, ExpiresSeconds = 60 });
        ReferenceBatchValidation.ValidateRequest(request with
            { SelectedReferences = [candidate with { Bytes = 32L * 1024 * 1024, SourceReference = "LICENSED" }], ExpiresSeconds = 3600 });
        ReferenceBatchRequest[] invalid =
        [
            request with { SchemaVersion = "reference_batch.v2" },
            request with { GoalId = "not-uuid" },
            request with { GoalId = Guid.Empty.ToString() },
            request with { CreativePackageId = "not-uuid" },
            request with { CreativePackageDigest = A.ToUpperInvariant() },
            request with { UserConfirmsPreviewAndRights = false },
            request with { ExpiresSeconds = 59 },
            request with { ExpiresSeconds = 3601 },
            request with { SelectedReferences = [] },
            request with { SelectedReferences = [.. twelve, candidate with { ShotId = "shot-13" }] },
            request with { SelectedReferences = [candidate, candidate with { InputRelativePath = "PicotooPet/references/b.jpg" }] },
            request with { SelectedReferences = [candidate, candidate with { ShotId = "shot-2", InputRelativePath = "PicotooPet/references/A.PNG" }] }
        ];
        foreach (var value in invalid) Reject(() => ReferenceBatchValidation.ValidateRequest(value));
        foreach (var value in new[]
        {
            candidate with { ShotId = "shot/1" }, candidate with { ShotId = new string('s', 81) },
            candidate with { Bytes = 0 }, candidate with { Bytes = 32L * 1024 * 1024 + 1 },
            candidate with { Sha256 = "abc" }, candidate with { SourceDigest = B.ToUpperInvariant() },
            candidate with { SourceReference = "WEB" }, candidate with { RightsScope = "gpu" },
            candidate with { InputRelativePath = "../a.png" },
            candidate with { InputRelativePath = "PicotooPet/references/../a.png" },
            candidate with { InputRelativePath = "PicotooPet/references/a.exe" },
            candidate with { InputRelativePath = "PicotooPet/references/a./b.png" },
            candidate with { InputRelativePath = "PicotooPet/references/a /b.png" },
            candidate with { InputRelativePath = "PicotooPet/references//b.png" },
            candidate with { InputRelativePath = "PicotooPet/references/C:a.png" }
        }) Reject(() => ReferenceBatchValidation.ValidateRequest(request with { SelectedReferences = [value] }));
    }

    private static void BindsEveryReceiptField()
    {
        var request = Request();
        var receipt = Receipt();
        foreach (var status in new[] { "Pending", "Approved", "Rejected", "Revoked", "Expired" })
            ReferenceBatchValidation.ValidateReceipt(request, receipt with { Status = status });
        foreach (var value in new[]
        {
            receipt with { SchemaVersion = "other" }, receipt with { GoalId = Package },
            receipt with { CreativePackageId = Goal }, receipt with { CreativePackageDigest = B },
            receipt with { ApprovalId = "fake" }, receipt with { BatchId = Guid.Empty.ToString() },
            receipt with { ApprovalRequestDigest = "fake" }, receipt with { Status = "Running" },
            receipt with { ExpiresAt = default }, receipt with { References = [] },
            receipt with { References = [receipt.References[0], receipt.References[0]] }
        }) Reject(() => ReferenceBatchValidation.ValidateReceipt(request, value));
        var registered = receipt.References[0];
        foreach (var value in new[]
        {
            registered with { AssetId = Guid.Empty.ToString() }, registered with { ShotId = "shot-2" },
            registered with { InputRelativePath = "PicotooPet/references/b.png" },
            registered with { Sha256 = B }, registered with { Bytes = 124 },
            registered with { SourceReference = "LICENSED" }, registered with { SourceDigest = A }
        }) Reject(() => ReferenceBatchValidation.ValidateReceipt(request, receipt with { References = [value] }));
    }

    private static void DerivesStableRequestKey()
    {
        var request = Request();
        var key = ReferenceBatchValidation.IdempotencyKey(request);
        SmokeAssert.True(key.Length is > 0 and <= 200, "Key outside server bounds");
        SmokeAssert.Equal(key, ReferenceBatchValidation.IdempotencyKey(Request()), "Same immutable request changed key");
        SmokeAssert.True(key != ReferenceBatchValidation.IdempotencyKey(request with { ExpiresSeconds = 60 }),
            "Changed exact request reused key");
        var second = request.SelectedReferences[0] with { ShotId = "shot-2", InputRelativePath = "PicotooPet/references/b.png" };
        var multiple = request with { SelectedReferences = [request.SelectedReferences[0], second] };
        SmokeAssert.Equal(ReferenceBatchValidation.IdempotencyKey(multiple),
            ReferenceBatchValidation.IdempotencyKey(multiple with { SelectedReferences = [second, request.SelectedReferences[0]] }),
            "Equivalent shot order changed canonical key");
    }

    private static async Task RejectsMismatchedServerReceiptAsync()
    {
        using var handler = new BatchHandler { Response = Receipt() with { GoalId = Package } };
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://core.invalid/") };
        await using var client = new MacCoreClient(http, "paired-reference-token");
        await RejectAsync(() => client.RegisterReferenceBatchAsync(Request(), "key", CancellationToken.None));
        SmokeAssert.Equal(1, handler.Calls.Count, "Invalid receipt triggered an approval or GPU command");
    }

    private static async Task RejectsInvalidGetAndOversizedReceiptAsync()
    {
        using var handler = new BatchHandler();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://core.invalid/") };
        await using var client = new MacCoreClient(http, "paired-reference-token");
        await RejectAsync(() => client.GetReferenceBatchAsync("not-uuid", CancellationToken.None));
        SmokeAssert.Equal(0, handler.Calls.Count, "Invalid approval identity reached HTTP");
        handler.Response = Receipt() with { ApprovalId = Batch };
        await RejectAsync(() => client.GetReferenceBatchAsync(Approval, CancellationToken.None));
        handler.Oversized = true;
        try
        {
            await client.GetReferenceBatchAsync(Approval, CancellationToken.None);
            throw new InvalidOperationException("Oversized receipt accepted");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal("RESPONSE_TOO_LARGE", exception.Code, "Reference response did not reuse bounded reader");
        }
    }

    private static async Task LostResponseRetryUsesOneRegistrationAsync()
    {
        using var handler = new BatchHandler { LoseFirstResponse = true };
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://core.invalid/") };
        await using var client = new MacCoreClient(http, "paired-reference-token");
        var request = Request();
        var key = ReferenceBatchValidation.IdempotencyKey(request);
        try
        {
            await client.RegisterReferenceBatchAsync(request, key, CancellationToken.None);
            throw new InvalidOperationException("Lost response unexpectedly succeeded");
        }
        catch (ApiException) { }
        SmokeAssert.Equal(1, handler.Calls.Count, "Client retried or issued another command without caller intent");
        var receipt = await client.RegisterReferenceBatchAsync(request, key, CancellationToken.None);
        SmokeAssert.Equal(Approval, receipt.ApprovalId, "Retry changed durable approval");
        SmokeAssert.Equal(1, handler.DurableCount, "Lost response retry duplicated registration");
        SmokeAssert.Equal(handler.Bodies[0], handler.Bodies[1], "Retry changed exact request bytes");
        SmokeAssert.Equal(handler.Keys[0], handler.Keys[1], "Retry changed idempotency key");
        SmokeAssert.True(handler.Calls.All(x => x == "POST /api/v1/production/references/batches"),
            "Registration delegated approval or GPU authority");
    }

    private static void Reject(Action action)
    {
        try { action(); }
        catch (ArgumentException) { return; }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("Invalid reference binding accepted");
    }

    private static async Task RejectAsync(Func<Task<ReferenceBatchReceipt>> action)
    {
        try { await action(); }
        catch (ArgumentException) { return; }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("Invalid server reference binding accepted");
    }

    private sealed class BatchHandler : HttpMessageHandler
    {
        private readonly Dictionary<string, string> durable = new(StringComparer.Ordinal);
        public ReferenceBatchReceipt Response { get; set; } = Receipt();
        public bool LoseFirstResponse { get; init; }
        public bool Oversized { get; set; }
        public List<string> Calls { get; } = [];
        public List<string> Bodies { get; } = [];
        public List<string> Keys { get; } = [];
        public string? Authorization { get; private set; }
        public bool TracePresent { get; private set; }
        public int DurableCount => durable.Count;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls.Add(request.Method + " " + request.RequestUri!.AbsolutePath);
            Authorization = request.Headers.Authorization?.ToString();
            TracePresent = request.Headers.TryGetValues("X-Picotoo-Trace-Id", out var trace) && trace.Single().Length > 0;
            if (request.Method == HttpMethod.Post)
            {
                var key = request.Headers.GetValues("Idempotency-Key").Single();
                var body = await request.Content!.ReadAsStringAsync(cancellationToken);
                Keys.Add(key);
                Bodies.Add(body);
                if (durable.TryGetValue(key, out var prior))
                    SmokeAssert.Equal(prior, body, "Same key used with a different batch");
                else durable.Add(key, body);
                if (LoseFirstResponse && Bodies.Count == 1) throw new HttpRequestException("simulated response lost");
            }
            var json = Oversized ? new string(' ', 128 * 1024 + 1) : JsonSerializer.Serialize(Response);
            return new HttpResponseMessage(request.Method == HttpMethod.Post ? HttpStatusCode.Created : HttpStatusCode.OK)
                { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        }
    }
}
