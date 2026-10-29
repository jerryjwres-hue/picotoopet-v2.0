using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// #164 phase-1 internal preflight ONLY, in the existing same EXE. This transports
/// assertions, not executable attestation. A Core-issued nonce and ordinary UI
/// Bearer are NOT enrollment, Worker identity, a Claim or GPU authorization.
/// No shipping factory call site: its unconditional proof-required hold remains.
/// </summary>
internal sealed class CoreWorkerChallengeClient : IDisposable
{
    private const string ExpectedDenial = "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED";
    private readonly ControlCenterSession _session;
    private readonly Action _requireCurrentSession;
    private readonly HttpClient _http;
    internal CoreWorkerChallengeClient(ControlCenterSession session, MacCoreClientOptions options, Action requireCurrentSession)
    {
        _session = session; _requireCurrentSession = requireCurrentSession;
        var uri = options.BaseUri;
        if (uri.Scheme is not ("http" or "https") || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0 || uri.AbsolutePath != "/")
            throw Invalid("CORE_CHALLENGE_ENDPOINT_INVALID");
        // Reuse session configuration and token; no second pairing/auth service.
        // Never follow a redirect (including same-origin) with a nonce/signature.
        _http = new(new SocketsHttpHandler
        {
            AllowAutoRedirect = false, UseCookies = false,
            ConnectTimeout = options.ConnectTimeout,
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            MaxConnectionsPerServer = 4,
        }) { BaseAddress = uri, Timeout = Timeout.InfiniteTimeSpan };
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", options.Token);
        _http.DefaultRequestHeaders.Accept.Add(new("application/json"));
        _http.DefaultRequestHeaders.CacheControl = new() { NoStore = true, NoCache = true };
    }

    // A return value describes EXPECTED DENIAL only. Errors/2xx never produce
    // success/admission, and nothing here calls claim, attempt, Comfy or recovery.
    internal async Task<string> RunExpectedDenyAsync(ProductionPlanRecord frozenPlan, string inputRoot,
        string keyRoot, string executorId, string expectedFingerprint, IReadOnlyDictionary<string, string> graphDigests,
        ProductionSubmissionJournal journal, CancellationToken ct)
    {
        // Freeze mutable array/dictionary containers before the first await.
        var plan = JsonSerializer.Deserialize<ProductionPlanRecord>(JsonSerializer.Serialize(frozenPlan))
            ?? throw Invalid("CORE_CHALLENGE_PLAN_INVALID");
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        var digest = Hash(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!));
        var graphs = graphDigests.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);
        if (plan.SchemaVersion != "1.1" || graphs.Count != plan.Tasks.Length
            || plan.Tasks.Any(t => !graphs.TryGetValue(t.ProductionTaskId, out var graph) || !IsHash(graph) || graph.All(c => c == '0')))
            throw Invalid("CORE_CHALLENGE_GRAPH_SCOPE_INVALID");
        var key = ProtectedWorkerSigningKey.Open(keyRoot, executorId, expectedFingerprint);
        _requireCurrentSession();
        using (journal.AcquireGpu()) RequireCleanJournal(journal, plan);
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct);
        budget.CancelAfter(TimeSpan.FromSeconds(30));
        var token = budget.Token;
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(plan.ProductionJobId);
        using var challengeDocument = await PostAsync(route + "/worker-challenge", new
        { worker_key_id = key.Identity.KeyId, executor_id = executorId, plan_digest = digest }, HttpStatusCode.OK, token).ConfigureAwait(false);
        var challenge = challengeDocument.RootElement;
        ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
        List<DurableReferenceSnapshot> snapshots = [];
        try
        {
            _requireCurrentSession();
            // Prepare and keep the existing crash-persistent copies/pins; no new
            // verifier, cryptography, executor, or journal implementation.
            using (journal.AcquireGpu())
            {
                RequireCleanJournal(journal, plan);
                var store = new ProductionReferenceSnapshotStore(inputRoot, (p, t, d) =>
                    new SessionBoundApproval(new CoreReferenceApprovalSource(_session, p.ProductionJobId, t.ProductionTaskId, d), _requireCurrentSession));
                foreach (var task in plan.Tasks)
                {
                    ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                    snapshots.Add(await store.PrepareAsync(plan, task, digest, graphs[task.ProductionTaskId], journal, token).ConfigureAwait(false));
                }
            }
            _requireCurrentSession();
            ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
            var witness = await BuildWitnessAsync(plan, digest, executorId, key.Identity.KeyId, challenge, snapshots, token).ConfigureAwait(false);
            _requireCurrentSession();
            var unsigned = JsonSerializer.SerializeToElement(witness);
            // Existing signer owns its existing GPU lock, actual file/approval
            // rechecks, DPAPI access and durable spent-nonce marker. Never retry.
            witness["signature"] = await key.SignMeasuredAsync(unsigned, plan, snapshots, journal, DateTimeOffset.UtcNow, token).ConfigureAwait(false);
            using (journal.AcquireGpu())
            {
                _requireCurrentSession();
                RequireCleanJournal(journal, plan);
                ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                foreach (var snapshot in snapshots) await snapshot.RecheckForWitnessAsync(token).ConfigureAwait(false);
                ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                // Retain snapshots + GPU lock through expected-deny POST. Neither
                // this response nor a software signature authorizes production.
                using var response = await PostAsync(route + "/witness/preflight", witness, HttpStatusCode.Conflict, token).ConfigureAwait(false);
                var error = response.RootElement;
                Shape(error, "error");
                var body = error.GetProperty("error");
                Shape(body, "code message retryable trace_id");
                if (body.GetProperty("code").ValueKind != JsonValueKind.String || body.GetProperty("code").GetString() != ExpectedDenial || body.GetProperty("retryable").ValueKind != JsonValueKind.False
                    || body.GetProperty("message").ValueKind != JsonValueKind.String || body.GetProperty("trace_id").ValueKind != JsonValueKind.String)
                    throw Invalid("CORE_PREFLIGHT_DENIAL_UNRECOGNIZED");
                _requireCurrentSession();
                return ExpectedDenial;
            }
        }
        finally { for (var i = snapshots.Count - 1; i >= 0; i--) snapshots[i].Dispose(); }
    }

    private static async Task<JsonObject> BuildWitnessAsync(ProductionPlanRecord plan, string digest, string executor,
        string keyId, JsonElement challenge, IReadOnlyList<DurableReferenceSnapshot> snapshots, CancellationToken ct)
    {
        var references = plan.Tasks.Select(task =>
        {
            var m = snapshots.Single(s => s.Measurement.TaskId == task.ProductionTaskId).Measurement;
            var r = task.ReferenceAsset ?? throw Invalid("CORE_CHALLENGE_REFERENCE_REQUIRED");
            return new { production_task_id = m.TaskId, shot_id = m.ShotId, asset_id = m.AssetId, approval_id = m.ApprovalId,
                approval_request_digest = r.ApprovalRequestDigest, source_sha256 = m.SourceSha256, source_bytes = m.SourceBytes,
                source_relative_path = r.InputRelativePath, snapshot_sha256 = m.SnapshotSha256, snapshot_bytes = m.SnapshotBytes,
                snapshot_receipt_sha256 = m.ReceiptSha256, graph_digest = m.GraphDigest, snapshot_relative_path = m.SnapshotRelativePath };
        }).ToArray();
        var executable = await ProductionLocalEnvironment.Sha256FileAsync(typeof(ProtectedWorkerSigningKey).Assembly.Location, ct).ConfigureAwait(false);
        return JsonSerializer.SerializeToNode(new
        {
            schema_version = "production.worker_witness.v1", algorithm = "ed25519", worker_key_id = keyId, executor_id = executor,
            production_job_id = plan.ProductionJobId, plan_digest = digest, nonce = challenge.GetProperty("nonce").GetString(),
            // Preserve Core's exact UTC microsecond instants; existing codec normalizes bytes.
            issued_at = challenge.GetProperty("issued_at").GetString(), expires_at = challenge.GetProperty("expires_at").GetString(),
            worker_executable_sha256 = executable, journal_digest = Hash("[]"u8.ToArray()), journal_generation = 0,
            journal_state = "NO_PRIOR_POST", references, signature = new string('a', 128),
        })!.AsObject();
    }

    private static void RequireCleanJournal(ProductionSubmissionJournal journal, ProductionPlanRecord plan)
    {
        if (journal.Pending().Count != 0 || plan.Tasks.Any(t => journal.Read(plan.ProductionJobId, t.ProductionTaskId) is not null))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
    }
    // Preserve the existing approval authority, but abort if session configuration
    // changes during any of its network awaits, including inside the reused signer.
    private sealed class SessionBoundApproval(ITrustedReferenceApprovalSource source, Action requireCurrent) : ITrustedReferenceApprovalSource
    {
        public async Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken ct)
        {
            requireCurrent();
            var approved = await source.IsApprovedAsync(descriptor, ct).ConfigureAwait(false);
            requireCurrent();
            return approved;
        }
    }
    private static void ValidateChallenge(JsonElement value, WorkerPublicIdentity identity, string executor, string job, string digest)
    {
        Shape(value, "schema_version worker_key_id executor_id production_job_id plan_digest nonce issued_at expires_at");
        if (value.EnumerateObject().Any(p => p.Value.ValueKind != JsonValueKind.String)) throw Invalid("CORE_CHALLENGE_SHAPE_INVALID");
        if (value.GetProperty("schema_version").GetString() != "production.worker_challenge.v1"
            || value.GetProperty("worker_key_id").GetString() != identity.KeyId || value.GetProperty("executor_id").GetString() != executor
            || value.GetProperty("production_job_id").GetString() != job || value.GetProperty("plan_digest").GetString() != digest
            || Hash(Convert.FromHexString(identity.PublicKeyHex)) != identity.Fingerprint || identity.KeyId != "wk-" + identity.Fingerprint[..40])
            throw Invalid("CORE_CHALLENGE_SCOPE_MISMATCH");
        var nonce = value.GetProperty("nonce").GetString();
        if (nonce is null || !IsHash(nonce) || nonce.All(c => c == '0')) throw Invalid("CORE_CHALLENGE_NONCE_INVALID");
        var issued = Utc(value.GetProperty("issued_at")); var expires = Utc(value.GetProperty("expires_at")); var now = DateTimeOffset.UtcNow;
        if (expires <= issued || expires - issued > TimeSpan.FromSeconds(30) || issued > now.AddSeconds(5) || expires <= now)
            throw Invalid("CORE_CHALLENGE_EXPIRED_OR_INVALID");
    }
    private static DateTimeOffset Utc(JsonElement value)
    {
        var text = value.GetString();
        if (text is null || text.Length > 40 || !Regex.IsMatch(text, @"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$", RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(100))
            || !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) || date.Offset != TimeSpan.Zero)
            throw Invalid("CORE_CHALLENGE_UTC_REQUIRED");
        return date;
    }
    private async Task<JsonDocument> PostAsync(string route, object payload, HttpStatusCode expected, CancellationToken ct)
    {
        _requireCurrentSession();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(10));
        using var request = new HttpRequestMessage(HttpMethod.Post, route) { Content = JsonContent.Create(payload) };
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false);
        if (response.StatusCode != expected) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_UNEXPECTED_STATUS");
        if (response.Content.Headers.ContentType?.MediaType != "application/json" || response.Content.Headers.ContentLength > 16384)
            throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_RESPONSE_INVALID");
        using var stream = await response.Content.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false);
        using var bytes = new MemoryStream();
        var buffer = new byte[4096]; int read;
        while ((read = await stream.ReadAsync(buffer, deadline.Token).ConfigureAwait(false)) != 0)
        {
            if (bytes.Length + read > 16384) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_RESPONSE_TOO_LARGE");
            bytes.Write(buffer, 0, read);
        }
        _requireCurrentSession();
        return JsonDocument.Parse(bytes.ToArray(), new() { MaxDepth = 16 });
    }
    private static void Shape(JsonElement value, string names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
        var expected = names.Split(' ').ToHashSet(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject()) if (!expected.Remove(property.Name)) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
        if (expected.Count != 0) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
    }
    private static bool IsHash(string text) => text.Length == 64 && text.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static InvalidDataException Invalid(string code) => new(code); // Never log response bodies, Bearer, nonce or seed.
    public void Dispose() => _http.Dispose();
}
