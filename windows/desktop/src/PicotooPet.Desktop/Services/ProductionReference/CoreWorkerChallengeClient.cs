using System.Globalization;
using System.Diagnostics;
using System.Reflection;
using System.Reflection.PortableExecutable;
using System.Reflection.Metadata;
using System.Buffers.Binary;
using System.Runtime.Loader;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
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
/// Existing same-EXE challenge transport and preserved expected-deny preflight. This transports
/// assertions, not executable attestation. A Core-issued nonce and ordinary UI
/// Bearer are NOT enrollment, Worker identity, a Claim or GPU authorization.
/// B admission reuses the prepared shipping snapshots and held GPU lease. Core's
/// explicitly enrolled operator-trusted policy is the admission authority.
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
        using var executable = await MeasureProcessImageAsync(ct).ConfigureAwait(false);
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
            var witness = await BuildWitnessAsync(plan, digest, executorId, key.Identity.KeyId, challenge, snapshots, executable, token).ConfigureAwait(false);
            _requireCurrentSession();
            await executable.RequireCurrentAsync(token).ConfigureAwait(false);
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
                await executable.RequireCurrentAsync(token).ConfigureAwait(false);
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

    internal async Task<ProductionClaimRecord> ClaimPreparedAsync(ProductionPlanRecord frozenPlan,
        string keyRoot, string executorId, string expectedFingerprint, IReadOnlyList<DurableReferenceSnapshot> preparedSnapshots,
        IReadOnlyDictionary<string, string> graphDigests, ProductionSubmissionJournal journal,
        ProductionSubmissionJournal.GpuLease gpu, CancellationToken ct)
    {
        gpu.RequireOwnedBy(journal);
        var plan = JsonSerializer.Deserialize<ProductionPlanRecord>(JsonSerializer.Serialize(frozenPlan))
            ?? throw Invalid("CORE_CHALLENGE_PLAN_INVALID");
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        var digest = Hash(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!));
        var graphs = graphDigests.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);
        var snapshots = preparedSnapshots.ToArray();
        if (plan.SchemaVersion != "1.1" || graphs.Count != plan.Tasks.Length
            || plan.Tasks.Any(t => !graphs.TryGetValue(t.ProductionTaskId, out var graph) || !IsHash(graph) || graph.All(c => c == '0'))
            || snapshots.Length != plan.Tasks.Count(t => t.RenderIntent == "IMAGE_TO_VIDEO")
            || snapshots.Any(s => !graphs.TryGetValue(s.Measurement.TaskId, out var graph) || graph != s.Measurement.GraphDigest))
            throw Invalid("CORE_CHALLENGE_GRAPH_SCOPE_INVALID");
        var pins = new List<IDisposable>();
        try
        {
            foreach (var snapshot in snapshots) pins.Add(snapshot.RetainForWitness());
            using var executable = await MeasureProcessImageAsync(ct).ConfigureAwait(false);
            var key = ProtectedWorkerSigningKey.Open(keyRoot, executorId, expectedFingerprint);
            _requireCurrentSession();
            RequireCleanJournal(journal, plan);
            using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct);
            budget.CancelAfter(TimeSpan.FromSeconds(30));
            var token = budget.Token;
            var route = "api/v1/production/jobs/" + Uri.EscapeDataString(plan.ProductionJobId);
            using var challengeDocument = await PostAsync(route + "/worker-challenge", new
            { worker_key_id = key.Identity.KeyId, executor_id = executorId, plan_digest = digest }, HttpStatusCode.OK, token).ConfigureAwait(false);
            var challenge = challengeDocument.RootElement;
            ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
            var witness = await BuildWitnessAsync(plan, digest, executorId, key.Identity.KeyId, challenge, snapshots, executable, token).ConfigureAwait(false);
            witness["signature"] = await key.SignMeasuredUnderLockAsync(JsonSerializer.SerializeToElement(witness), plan,
                snapshots, journal, gpu, DateTimeOffset.UtcNow, token).ConfigureAwait(false);
            _requireCurrentSession();
            gpu.RequireOwnedBy(journal);
            RequireCleanJournal(journal, plan);
            foreach (var snapshot in snapshots) await snapshot.RecheckForWitnessAsync(token).ConfigureAwait(false);
            await executable.RequireCurrentAsync(token).ConfigureAwait(false);
            ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
            _requireCurrentSession();
            var claim = await _session.ClaimProductionJobWithWorkerWitnessAsync(plan.ProductionJobId, executorId,
                JsonSerializer.SerializeToElement(witness), token).ConfigureAwait(false);
            _requireCurrentSession();
            gpu.RequireOwnedBy(journal);
            if (claim.ProductionJobId != plan.ProductionJobId || claim.ExecutorId != executorId
                || string.IsNullOrWhiteSpace(claim.LeaseToken) || claim.LeaseExpiresAt <= DateTimeOffset.UtcNow
                || claim.Tasks.Length != plan.Tasks.Length || claim.Plan.Tasks.Length != plan.Tasks.Length
                || claim.Tasks.Any(t => t.ProductionJobId != plan.ProductionJobId || t.Status != "Pending"
                    || t.AttemptCount != 0 || t.ComfyPromptId is not null
                    || !plan.Tasks.Any(p => p.ProductionTaskId == t.ProductionTaskId && p == t.TaskPlan))
                || Hash(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(claim.Plan)!)) != digest)
                throw Invalid("CORE_PILOT_CLAIM_SCOPE_INVALID");
            return claim;
        }
        finally { for (var i = pins.Count - 1; i >= 0; i--) pins[i].Dispose(); }
    }

    // 01. Explicit LTX reservation, deliberately not invoked by the shipping
    //     dispatch loop until renderer settlement and recovery are connected.
    internal sealed record LtxClaim(string JobId, string TaskId, string AttemptId,
        string ExecutorId, string LeaseToken, DateTimeOffset ExpiresAt,
        string PlanDigest, string IntentDigest, JsonElement Plan)
    {
        public override string ToString() => "LTX claim (credentials redacted)";
    }

    internal async Task<LtxClaim> ClaimLtxPreparedAsync(ProductionReferenceAssetV11Record reference,
        string planDigest, string vendorIntentDigest, string keyRoot, string executorId,
        string expectedFingerprint, DurableReferenceSnapshot snapshot,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu, CancellationToken ct)
    {
        gpu.RequireOwnedBy(journal);
        using var pin = snapshot.RetainForWitness();
        if (!Guid.TryParseExact(reference.ProductionJobId, "D", out _)
            || !Guid.TryParseExact(reference.ProductionTaskId, "D", out _)
            || reference.RightsScope != "ltx.desktop.local.i2v.production.v1"
            || !IsHash(planDigest) || !IsHash(vendorIntentDigest)
            || snapshot.Measurement.PlanDigest != planDigest
            || snapshot.Measurement.GraphDigest != vendorIntentDigest)
            throw Invalid("LTX_CLAIM_SCOPE_INVALID");
        if (journal.Pending().Count != 0 || journal.Read(reference.ProductionJobId, reference.ProductionTaskId) is not null)
            throw Invalid("LTX_CLAIM_RECONCILIATION_REQUIRED");

        // 02. Check exact live consent before creating the one-use challenge.
        var authority = LtxReferenceApproval(reference, planDigest, vendorIntentDigest);
        var descriptor = new TrustedReferenceDescriptor(reference.ApprovalId, reference.ShotId,
            reference.AssetId, reference.InputRelativePath, reference.Sha256, reference.Bytes);
        if (!await authority.IsApprovedAsync(descriptor, ct).ConfigureAwait(false))
            throw Invalid("LTX_REFERENCE_APPROVAL_REQUIRED");
        await snapshot.RecheckForWitnessAsync(ct).ConfigureAwait(false);
        var key = ProtectedWorkerSigningKey.Open(keyRoot, executorId, expectedFingerprint);
        using var executable = await MeasureProcessImageAsync(ct).ConfigureAwait(false);
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct);
        budget.CancelAfter(TimeSpan.FromSeconds(30));
        var token = budget.Token;
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(reference.ProductionJobId);
        using var challengeDocument = await PostAsync(route + "/ltx-worker-challenge",
            new { worker_key_id = key.Identity.KeyId, executor_id = executorId, plan_digest = planDigest },
            HttpStatusCode.OK, token).ConfigureAwait(false);
        var challenge = challengeDocument.RootElement;
        ValidateChallenge(challenge, key.Identity, executorId, reference.ProductionJobId, planDigest, true);
        var witness = await BuildMeasuredWitnessAsync("production.ltx.worker_witness.v1",
            reference.ProductionJobId, planDigest, executorId, key.Identity.KeyId, challenge,
            [(reference, snapshot)], executable, token).ConfigureAwait(false);
        witness["signature"] = await key.SignLtxMeasuredUnderLockAsync(JsonSerializer.SerializeToElement(witness),
            reference, planDigest, vendorIntentDigest, snapshot, journal, gpu, DateTimeOffset.UtcNow, token)
            .ConfigureAwait(false);
        await snapshot.RecheckForWitnessAsync(token).ConfigureAwait(false);
        await executable.RequireCurrentAsync(token).ConfigureAwait(false);
        ValidateChallenge(challenge, key.Identity, executorId, reference.ProductionJobId, planDigest, true);
        _requireCurrentSession();
        gpu.RequireOwnedBy(journal);
        if (journal.Pending().Count != 0 || journal.Read(reference.ProductionJobId, reference.ProductionTaskId) is not null)
            throw Invalid("LTX_CLAIM_RECONCILIATION_REQUIRED");

        // 03. Persist ambiguity BEFORE sending the claim. Never replay after
        //     a lost response, or treat this as a vendor generation ID.
        var marker = new ProductionSubmission(reference.ProductionJobId, reference.ProductionTaskId,
            planDigest, vendorIntentDigest, "Claiming", null, Renderer: ProductionSubmission.LtxRenderer);
        token.ThrowIfCancellationRequested();
        journal.Save(marker);
        using var response = await PostAsync(route + "/ltx-claim", witness, HttpStatusCode.OK, token)
            .ConfigureAwait(false);
        var claim = ReadLtxClaim(response.RootElement, reference, executorId, planDigest, vendorIntentDigest);
        gpu.RequireOwnedBy(journal);
        journal.Save(marker with { Phase = "Claimed" });
        return claim;
    }

    internal static LtxClaim ReadLtxClaim(JsonElement body, ProductionReferenceAssetV11Record reference,
        string executor, string planDigest, string intentDigest)
    {
        Shape(body, "schema_version production_job_id production_task_id production_attempt_id executor_id lease_token lease_expires_at plan_digest vendor_intent_digest plan");
        var plan = body.GetProperty("plan");
        var attempt = body.GetProperty("production_attempt_id").GetString();
        var token = body.GetProperty("lease_token").GetString();
        var expires = Utc(body.GetProperty("lease_expires_at"));
        if (body.GetProperty("schema_version").GetString() != "production.ltx.claim.v1"
            || body.GetProperty("production_job_id").GetString() != reference.ProductionJobId
            || body.GetProperty("production_task_id").GetString() != reference.ProductionTaskId
            || body.GetProperty("executor_id").GetString() != executor
            || body.GetProperty("plan_digest").GetString() != planDigest
            || body.GetProperty("vendor_intent_digest").GetString() != intentDigest
            || !Guid.TryParseExact(attempt, "D", out _)
            || string.IsNullOrWhiteSpace(token) || token.Length > 200 || expires <= DateTimeOffset.UtcNow
            || Hash(CanonicalJson.Serialize(JsonNode.Parse(plan.GetRawText())!)) != planDigest
            || plan.GetProperty("schema_version").GetString() != "1.2"
            || plan.GetProperty("production_profile").GetString() != "production.ltx.desktop.local.v1"
            || plan.GetProperty("production_job_id").GetString() != reference.ProductionJobId
            || plan.GetProperty("production_task_id").GetString() != reference.ProductionTaskId
            || plan.GetProperty("reference_asset").Deserialize<ProductionReferenceAssetV11Record>() != reference)
            throw Invalid("LTX_CLAIM_RECEIPT_INVALID");
        return new(reference.ProductionJobId, reference.ProductionTaskId, attempt!, executor,
            token!, expires, planDigest, intentDigest, plan.Clone());
    }

    // 04. Bind only the vendor IDs already persisted by the existing LTX
    //     submission transport. A lost Core response permits exact rebind,
    //     never another upload or generation. No media success is asserted.
    internal async Task BindLtxGenerationAsync(LtxClaim claim,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        CancellationToken ct)
    {
        gpu.RequireOwnedBy(journal);
        var marker = journal.Read(claim.JobId, claim.TaskId);
        if (marker is null || !marker.IsLtx || marker.Phase != "Submitted"
            || marker.PlanDigest != claim.PlanDigest || marker.GraphDigest != claim.IntentDigest
            || !Guid.TryParseExact(marker.PromptId, "D", out var generation)
            || !Guid.TryParseExact(marker.VendorStartFrameAssetId, "D", out var asset)
            || generation == Guid.Empty || asset == Guid.Empty)
            throw Invalid("LTX_VENDOR_BIND_JOURNAL_SCOPE_INVALID");
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(claim.JobId) + "/ltx-vendor/bind";
        using var result = await PostAsync(route, new { executor_id = claim.ExecutorId, lease_token = claim.LeaseToken,
            production_attempt_id = claim.AttemptId, plan_digest = claim.PlanDigest,
            vendor_intent_digest = claim.IntentDigest, generation_id = generation.ToString("D"),
            start_frame_asset_id = asset.ToString("D") }, HttpStatusCode.OK, ct).ConfigureAwait(false);
        var receipt = result.RootElement;
        Shape(receipt, "schema_version production_job_id production_task_id production_attempt_id plan_digest vendor_intent_digest generation_id start_frame_asset_id");
        if (receipt.GetProperty("schema_version").GetString() != "production.ltx.vendor_binding.v1"
            || receipt.GetProperty("production_job_id").GetString() != claim.JobId
            || receipt.GetProperty("production_task_id").GetString() != claim.TaskId
            || receipt.GetProperty("production_attempt_id").GetString() != claim.AttemptId
            || receipt.GetProperty("plan_digest").GetString() != claim.PlanDigest
            || receipt.GetProperty("vendor_intent_digest").GetString() != claim.IntentDigest
            || receipt.GetProperty("generation_id").GetString() != generation.ToString("D")
            || receipt.GetProperty("start_frame_asset_id").GetString() != asset.ToString("D"))
            throw Invalid("LTX_VENDOR_BIND_RECEIPT_INVALID");
        gpu.RequireOwnedBy(journal);
        // 05. Preserve Submitted until decoded media and Core settlement.
    }

    // 06. Collect the exact already-submitted local generation. This does not
    //     submit or retry a render. The existing final QA process runner is reused.
    //     Caller owns the shared GPU lock; no separate renderer or worker.
    internal async Task<JsonElement> CollectCompletedLtxCandidateAsync(LtxClaim claim,
        LtxDesktopLocalI2vPreflightClient vendor, string outputRoot,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        CancellationToken ct)
    {
        gpu.RequireOwnedBy(journal);
        var marker = journal.Read(claim.JobId, claim.TaskId);
        if (marker is null || !marker.IsLtx || marker.Phase != "Submitted"
            || marker.PlanDigest != claim.PlanDigest || marker.GraphDigest != claim.IntentDigest
            || !Guid.TryParseExact(claim.JobId, "D", out _)
            || !Guid.TryParseExact(claim.TaskId, "D", out _)
            || !Guid.TryParseExact(marker.PromptId, "D", out _)
            || !Guid.TryParseExact(marker.VendorStartFrameAssetId, "D", out _))
            throw Invalid("LTX_COLLECT_JOURNAL_SCOPE_INVALID");
        if (!MasterVideoPathPolicy.IsSafeLocalFullyQualified(outputRoot) || !Directory.Exists(outputRoot))
            throw Invalid("LTX_COLLECT_ROOT_INVALID");
        // 07. Retain the same local output root; never accept a vendor path.
        for (DirectoryInfo? parent = new(outputRoot); parent is not null; parent = parent.Parent)
            if ((parent.Attributes & FileAttributes.ReparsePoint) != 0)
                throw Invalid("LTX_COLLECT_ROOT_INVALID");
        var directory = Path.GetFullPath(outputRoot);
        foreach (var part in new[] { "PicotooPet", "ltx", claim.JobId, claim.TaskId })
        {
            directory = Path.Combine(directory, part);
            ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, directory);
            Directory.CreateDirectory(directory);
            ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, directory);
        }
        await CheckLtxLeaseAsync(claim, journal, gpu, true, ct).ConfigureAwait(false);
        await BindLtxGenerationAsync(claim, journal, gpu, ct).ConfigureAwait(false);
        var expected = new LtxDesktopGenerationExpectation(marker.PromptId!, marker.VendorStartFrameAssetId!,
            claim.Plan.GetProperty("prompt").GetString() ?? throw Invalid("LTX_COLLECT_PLAN_INVALID"),
            claim.Plan.GetProperty("seed").GetInt32());
        var candidate = await vendor.ExportCompletedCandidateAsync(expected, directory, ct).ConfigureAwait(false);
        var inspection = candidate.Inspection;
        var fileName = expected.GenerationId + "-video-" + inspection.VideoAssetId + ".mp4";
        if (!inspection.ResultIsLocal || inspection.Lane != "local" || !inspection.MediaBytesDownloaded
            || inspection.GenerationId != expected.GenerationId || inspection.MediaType != "video/mp4"
            || !Guid.TryParseExact(inspection.VideoAssetId, "D", out _)
            || candidate.LocalFileName != fileName)
            throw Invalid("LTX_COLLECT_MEDIA_UNVERIFIED");
        var file = Path.Combine(directory, fileName);
        ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, file);
        // 08. Hold the downloaded bytes against writes across the real decode
        //     AND Core settlement. An exported header alone is not a video pass.
        await using var pin = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read);
        var facts = await new FinalVideoQaMediaProbe(new FixedMasterVideoProcessRunner())
            .VerifyLtxCandidateAsync(file, candidate.Sha256, candidate.Bytes, ct).ConfigureAwait(false);
        await CheckLtxLeaseAsync(claim, journal, gpu, false, ct).ConfigureAwait(false);
        var relative = "PicotooPet/ltx/" + claim.JobId + "/" + claim.TaskId + "/" + fileName;
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(claim.JobId) + "/ltx-candidate/result";
        using var response = await PostAsync(route, new
        {
            executor_id = claim.ExecutorId, lease_token = claim.LeaseToken,
            production_attempt_id = claim.AttemptId, plan_digest = claim.PlanDigest,
            vendor_intent_digest = claim.IntentDigest, generation_id = expected.GenerationId,
            start_frame_asset_id = expected.StartFrameAssetId, video_asset_id = inspection.VideoAssetId,
            output_relpath = relative, output_sha256 = candidate.Sha256, output_bytes = candidate.Bytes,
            mime_type = "video/mp4", width = facts.Width, height = facts.Height,
            frame_count = facts.FrameCount, fps = facts.Fps, duration_ms = facts.DurationMs,
            lane = "local", decode_verified = true,
        }, HttpStatusCode.OK, ct).ConfigureAwait(false);
        var body = response.RootElement;
        Shape(body, "schema_version production_job_id production_task_id production_attempt_id plan_digest vendor_intent_digest generation_id start_frame_asset_id video_asset_id output_relpath output_sha256 output_bytes mime_type width height frame_count fps duration_ms lane decode_verified job_status review_required mac_bytes_verified");
        if (body.GetProperty("schema_version").GetString() != "production.ltx.candidate.v1"
            || body.GetProperty("production_job_id").GetString() != claim.JobId
            || body.GetProperty("production_task_id").GetString() != claim.TaskId
            || body.GetProperty("production_attempt_id").GetString() != claim.AttemptId
            || body.GetProperty("plan_digest").GetString() != claim.PlanDigest
            || body.GetProperty("vendor_intent_digest").GetString() != claim.IntentDigest
            || body.GetProperty("generation_id").GetString() != expected.GenerationId
            || body.GetProperty("start_frame_asset_id").GetString() != expected.StartFrameAssetId
            || body.GetProperty("video_asset_id").GetString() != inspection.VideoAssetId
            || body.GetProperty("output_relpath").GetString() != relative
            || body.GetProperty("output_sha256").GetString() != candidate.Sha256
            || body.GetProperty("output_bytes").GetInt64() != candidate.Bytes
            || body.GetProperty("mime_type").GetString() != "video/mp4"
            || body.GetProperty("width").GetInt32() != facts.Width || body.GetProperty("height").GetInt32() != facts.Height
            || body.GetProperty("frame_count").GetInt32() != facts.FrameCount || body.GetProperty("fps").GetInt32() != facts.Fps
            || body.GetProperty("duration_ms").GetInt32() != facts.DurationMs
            || body.GetProperty("lane").GetString() != "local" || !body.GetProperty("decode_verified").GetBoolean()
            || body.GetProperty("job_status").GetString() != "NeedsHuman"
            || !body.GetProperty("review_required").GetBoolean() || body.GetProperty("mac_bytes_verified").GetBoolean())
            throw Invalid("LTX_COLLECT_RECEIPT_INVALID");
        gpu.RequireOwnedBy(journal);
        // 09. Only an exact durable Core receipt clears the pending marker.
        //     Lost responses retain Submitted; never replace the output file.
        journal.Save(marker with { Phase = "Settled" });
        return body.Clone();
    }

    // 04. Existing paired transport, same reservation; no additional claim.
    internal async Task<DateTimeOffset> CheckLtxLeaseAsync(LtxClaim claim,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        bool renew, CancellationToken ct)
    {
        gpu.RequireOwnedBy(journal);
        var marker = journal.Read(claim.JobId, claim.TaskId);
        if (marker is null || !marker.IsLtx || marker.Phase is not ("Claimed" or "Submitting" or "Submitted")
            || marker.PlanDigest != claim.PlanDigest || marker.GraphDigest != claim.IntentDigest)
            throw Invalid("LTX_LEASE_JOURNAL_SCOPE_INVALID");
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(claim.JobId)
            + (renew ? "/ltx-lease/heartbeat" : "/ltx-lease/recheck");
        using var result = await PostAsync(route, new { executor_id = claim.ExecutorId, lease_token = claim.LeaseToken,
            production_attempt_id = claim.AttemptId, plan_digest = claim.PlanDigest,
            vendor_intent_digest = claim.IntentDigest }, HttpStatusCode.OK, ct).ConfigureAwait(false);
        var receipt = result.RootElement;
        Shape(receipt, "schema_version production_job_id production_task_id production_attempt_id plan_digest vendor_intent_digest lease_expires_at");
        var expires = Utc(receipt.GetProperty("lease_expires_at"));
        if (receipt.GetProperty("schema_version").GetString() != "production.ltx.lease.v1"
            || receipt.GetProperty("production_job_id").GetString() != claim.JobId
            || receipt.GetProperty("production_task_id").GetString() != claim.TaskId
            || receipt.GetProperty("production_attempt_id").GetString() != claim.AttemptId
            || receipt.GetProperty("plan_digest").GetString() != claim.PlanDigest
            || receipt.GetProperty("vendor_intent_digest").GetString() != claim.IntentDigest
            || expires <= DateTimeOffset.UtcNow)
            throw Invalid("LTX_LEASE_RECEIPT_INVALID");
        gpu.RequireOwnedBy(journal);
        return expires;
    }

    private static async Task<JsonObject> BuildWitnessAsync(ProductionPlanRecord plan, string digest, string executor,
        string keyId, JsonElement challenge, IReadOnlyList<DurableReferenceSnapshot> snapshots, ProcessImageMeasurement image, CancellationToken ct)
    {
        var pairs = plan.Tasks.Where(t => t.RenderIntent == "IMAGE_TO_VIDEO").Select(task =>
            (task.ReferenceAsset ?? throw Invalid("CORE_CHALLENGE_REFERENCE_REQUIRED"),
             snapshots.Single(s => s.Measurement.TaskId == task.ProductionTaskId))).ToArray();
        return await BuildMeasuredWitnessAsync("production.worker_witness.v1", plan.ProductionJobId,
            digest, executor, keyId, challenge, pairs, image, ct).ConfigureAwait(false);
    }

    // 05. Share the witness serialization, not the renderer signature domain.
    private static async Task<JsonObject> BuildMeasuredWitnessAsync(string schema, string jobId, string digest,
        string executor, string keyId, JsonElement challenge,
        IReadOnlyList<(ProductionReferenceAssetV11Record Reference, DurableReferenceSnapshot Snapshot)> pairs,
        ProcessImageMeasurement image, CancellationToken ct)
    {
        var references = pairs.Select(pair =>
        {
            var m = pair.Snapshot.Measurement;
            var r = pair.Reference;
            return new { production_task_id = m.TaskId, shot_id = m.ShotId, asset_id = m.AssetId, approval_id = m.ApprovalId,
                approval_request_digest = r.ApprovalRequestDigest, source_sha256 = m.SourceSha256, source_bytes = m.SourceBytes,
                source_relative_path = r.InputRelativePath, snapshot_sha256 = m.SnapshotSha256, snapshot_bytes = m.SnapshotBytes,
                snapshot_receipt_sha256 = m.ReceiptSha256, graph_digest = m.GraphDigest, snapshot_relative_path = m.SnapshotRelativePath };
        }).ToArray();
        await image.RequireCurrentAsync(ct).ConfigureAwait(false);
        var executable = image.Sha256;
        return JsonSerializer.SerializeToNode(new
        {
            schema_version = schema, algorithm = "ed25519", worker_key_id = keyId, executor_id = executor,
            production_job_id = jobId, plan_digest = digest, nonce = challenge.GetProperty("nonce").GetString(),
            // Preserve Core's exact UTC microsecond instants; existing codec normalizes bytes.
            issued_at = challenge.GetProperty("issued_at").GetString(), expires_at = challenge.GetProperty("expires_at").GetString(),
            worker_executable_sha256 = executable, journal_digest = Hash("[]"u8.ToArray()), journal_generation = 0,
            journal_state = "NO_PRIOR_POST", references, signature = new string('a', 128),
        })!.AsObject();
    }


    // A local integrity measurement, never a vendor signature or remote attestation.
    // No caller-provided path/hash is accepted by this production entrypoint.
    internal static async Task<ProcessImageMeasurement> MeasureProcessImageAsync(CancellationToken ct)
    {
        var path = CurrentImagePath();
        var image = await OpenExecutableFileAsync(path, ct).ConfigureAwait(false);
        try { await image.RequireCurrentAsync(ct).ConfigureAwait(false); return image; }
        catch { image.Dispose(); throw; }
    }

    private static string CurrentImagePath()
    {
        if (!OperatingSystem.IsWindows()) throw Invalid("WORKER_EXE_WINDOWS_REQUIRED");
        using var process = Process.GetCurrentProcess();
        var buffer = new char[32768]; var size = buffer.Length;
        if (!QueryFullProcessImageNameW(process.SafeHandle, 0, buffer, ref size) || size <= 0 || size > buffer.Length) throw Invalid("WORKER_EXE_OS_PATH_UNVERIFIED");
        var osPath = CanonicalExecutablePath(new string(buffer, 0, size));
        var reported = Environment.ProcessPath;
        if (reported is null || !string.Equals(osPath, CanonicalExecutablePath(reported), StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_PROCESS_PATH_MISMATCH");
        return osPath;
    }

    // Both apphost forms bind the real runtime entry to bytes under the image
    // lease. No Assembly.Location call (or reflective substitute): bundled entry
    // modules have no such file. This is local binding, NOT remote attestation.
    private static void RequireEntryBinding(string path, FileStream image, Assembly? entry, string baseDirectory)
    {
        var name = entry?.GetName().Name;
        if (entry is null || entry.IsDynamic || name is not ("Picotoo Pet AI" or "PicotooPet.MediaWorker.SmokeTests")
            || AssemblyLoadContext.GetLoadContext(entry) != AssemblyLoadContext.Default
            || !string.Equals(System.IO.Path.GetFileName(path), name + ".exe", StringComparison.OrdinalIgnoreCase)
            || !System.IO.Path.IsPathFullyQualified(baseDirectory)
            || !string.Equals(baseDirectory, System.IO.Path.GetFullPath(baseDirectory), StringComparison.OrdinalIgnoreCase)
            || !string.Equals(System.IO.Path.TrimEndingDirectorySeparator(baseDirectory), System.IO.Path.GetDirectoryName(path), StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_HOST_UNVERIFIED");
        // Retain the SDK Win32 resource negative filter, now under the pinned file.
        var original = FileVersionInfo.GetVersionInfo(path).OriginalFilename;
        if (!string.Equals(original, name + ".dll", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(original, name + ".exe", StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_APPHOST_BINDING_UNVERIFIED");
        image.Position = 0;
        int nativeSize;
        using (var pe = new PEReader(image, PEStreamOptions.LeaveOpen))
        {
            nativeSize = pe.PEHeaders.PEHeader?.SizeOfHeaders ?? 0;
            foreach (var section in pe.PEHeaders.SectionHeaders)
            {
                if (section.PointerToRawData < 0 || section.SizeOfRawData < 0) throw Invalid("WORKER_EXE_APPHOST_INVALID");
                nativeSize = Math.Max(nativeSize, checked(section.PointerToRawData + section.SizeOfRawData));
            }
        }
        if (nativeSize <= 0 || nativeSize > 32 * 1024 * 1024 || nativeSize > image.Length) throw Invalid("WORKER_EXE_APPHOST_INVALID");
        image.Position = 0; var native = new byte[nativeSize]; image.ReadExactly(native);
        // .NET HostModel bundle marker; offset zero denotes an ordinary SDK
        // apphost. Search only the bounded native PE, never arbitrary payloads.
        ReadOnlySpan<byte> marker = [0x8b,0x12,0x02,0xb9,0x6a,0x61,0x20,0x38,0x72,0x7b,0x93,0x02,0x14,0xd7,0xa0,0x32,
            0x13,0xf5,0xb9,0xe6,0xef,0xae,0x33,0x18,0xee,0x3b,0x2d,0xce,0x24,0xb3,0x6a,0xae];
        var index = native.AsSpan().IndexOf(marker);
        if (index < 8 || native.AsSpan(index + marker.Length).IndexOf(marker) >= 0
            || native.AsSpan().IndexOf(Encoding.UTF8.GetBytes(name + ".dll\0")) < 0)
            throw Invalid("WORKER_EXE_APPHOST_BINDING_UNVERIFIED");
        var header = BinaryPrimitives.ReadInt64LittleEndian(native.AsSpan(index - 8, 8));
        if (header == 0)
        {
            var dll = System.IO.Path.Combine(baseDirectory, name + ".dll");
            ProductionLocalEnvironment.AssertNoLinkEscape(baseDirectory, dll);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(dll)) throw Invalid("WORKER_EXE_ENTRY_FILE_UNVERIFIED");
            using var file = new FileStream(dll, FileMode.Open, FileAccess.Read, FileShare.Read);
            RequireFinalPath(file.SafeFileHandle, dll); var before = Stamp(file.SafeFileHandle);
            using var pe = new PEReader(file, PEStreamOptions.LeaveOpen);
            RequireEntryMetadata(pe, entry);
            if (before != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_ENTRY_CHANGED");
            RequireFinalPath(file.SafeFileHandle, dll);
            return;
        }
        // Only the actual supported .NET v6.0, uncompressed bundle format is
        // admitted. Unknown formats/flags fail closed, never fall back to a DLL.
        if (header < nativeSize || header >= image.Length || image.Length - header > 1024 * 1024)
            throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        image.Position = header; var manifest = new byte[checked((int)(image.Length - header))]; image.ReadExactly(manifest);
        using var reader = new BinaryReader(new MemoryStream(manifest), new UTF8Encoding(false, true));
        if (reader.ReadUInt32() != 6 || reader.ReadUInt32() != 0) throw Invalid("WORKER_EXE_BUNDLE_VERSION_UNVERIFIED");
        var count = reader.ReadInt32();
        if (count <= 0 || count > 4096) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        _ = ReadBundleName(reader, 128);
        for (var i = 0; i < 2; i++)
        {
            var offset = reader.ReadInt64(); var size = reader.ReadInt64();
            if (offset < nativeSize || size <= 0 || offset > header || size > header - offset) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        }
        if (reader.ReadUInt64() != 0) throw Invalid("WORKER_EXE_BUNDLE_FLAGS_UNVERIFIED");
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long entryOffset = 0; var entrySize = 0;
        for (var i = 0; i < count; i++)
        {
            var offset = reader.ReadInt64(); var size = reader.ReadInt64(); var compressed = reader.ReadInt64(); var type = reader.ReadByte();
            var relative = ReadBundleName(reader, 1024);
            if (offset < nativeSize || size <= 0 || offset > header || size > header - offset || compressed != 0 || type > 5
                || !names.Add(relative) || relative.Contains(':', StringComparison.Ordinal) || relative.Contains('\\', StringComparison.Ordinal)
                || relative.Split('/').Any(part => part is "" or "." or "..")) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
            if (relative == name + ".dll")
            {
                if (type != 1 || size > 64 * 1024 * 1024) throw Invalid("WORKER_EXE_BUNDLE_ENTRY_UNVERIFIED");
                entryOffset = offset; entrySize = checked((int)size);
            }
        }
        if (entrySize == 0) throw Invalid("WORKER_EXE_BUNDLE_ENTRY_UNVERIFIED");
        image.Position = entryOffset; var bytes = new byte[entrySize]; image.ReadExactly(bytes);
        using var embedded = new PEReader(new MemoryStream(bytes));
        RequireEntryMetadata(embedded, entry);
    }
    private static string ReadBundleName(BinaryReader reader, int maximum)
    {
        var length = reader.Read7BitEncodedInt();
        if (length <= 0 || length > maximum || length > reader.BaseStream.Length - reader.BaseStream.Position)
            throw Invalid("WORKER_EXE_BUNDLE_STRING_UNVERIFIED");
        return new UTF8Encoding(false, true).GetString(reader.ReadBytes(length));
    }
    private static void RequireEntryMetadata(PEReader pe, Assembly entry)
    {
        if (!pe.HasMetadata) throw Invalid("WORKER_EXE_ENTRY_METADATA_UNVERIFIED");
        var metadata = pe.GetMetadataReader();
        if (!metadata.IsAssembly || metadata.GetString(metadata.GetAssemblyDefinition().Name) != entry.GetName().Name
            || metadata.GetAssemblyDefinition().Version != entry.GetName().Version
            || metadata.GetGuid(metadata.GetModuleDefinition().Mvid) == Guid.Empty
            || metadata.GetGuid(metadata.GetModuleDefinition().Mvid) != entry.ManifestModule.ModuleVersionId)
            throw Invalid("WORKER_EXE_ENTRY_METADATA_UNVERIFIED");
    }
    private static string CanonicalExecutablePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !System.IO.Path.IsPathFullyQualified(path)
            || path.StartsWith(@"\\", StringComparison.Ordinal) || path.Contains('/', StringComparison.Ordinal)
            || path.Length < 4 || path[1] != ':' || path[2] != '\\' || path[3..].Contains(':', StringComparison.Ordinal)
            || !string.Equals(path, System.IO.Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase)
            || !string.Equals(System.IO.Path.GetExtension(path), ".exe", StringComparison.OrdinalIgnoreCase)
            || string.Equals(System.IO.Path.GetFileName(path), "dotnet.exe", StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_PATH_UNVERIFIED");
        var root = System.IO.Path.GetPathRoot(path)!;
        var drive = new DriveInfo(root);
        // This bounded implementation relies on local NTFS file identity/sharing.
        if (drive.DriveType != DriveType.Fixed || drive.DriveFormat != "NTFS") throw Invalid("WORKER_EXE_FILESYSTEM_UNVERIFIED");
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)) throw Invalid("WORKER_EXE_NOT_ORDINARY");
        return path;
    }
    private static async Task<ProcessImageMeasurement> OpenExecutableFileAsync(string path, CancellationToken ct)
    {
        path = CanonicalExecutablePath(path);
        var parents = new WorkerKeyNamespace(System.IO.Path.GetDirectoryName(path)!);
        FileStream? file = null;
        try
        {
            // Read-only sharing denies writers/deletion while the existing path
            // hasher opens its own read handle. Parent pins deny namespace rename.
            file = new(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            RequireFinalPath(file.SafeFileHandle, path);
            var before = Stamp(file.SafeFileHandle);
            using (var pe = new PEReader(file, PEStreamOptions.LeaveOpen))
            {
                var header = pe.PEHeaders;
                var machine = RuntimeInformation.ProcessArchitecture switch
                {
                    Architecture.X64 => Machine.Amd64, Architecture.X86 => Machine.I386,
                    Architecture.Arm64 => Machine.Arm64, _ => throw Invalid("WORKER_EXE_ARCH_UNSUPPORTED"),
                };
                if (pe.HasMetadata || header.PEHeader is null || header.CoffHeader.Machine != machine
                    || (header.CoffHeader.Characteristics & Characteristics.ExecutableImage) == 0
                    || (header.CoffHeader.Characteristics & Characteristics.Dll) != 0
                    || header.PEHeader.AddressOfEntryPoint <= 0 || header.PEHeader.SizeOfImage <= 0)
                    throw Invalid("WORKER_EXE_NOT_PE_EXECUTABLE");
            }
            if (string.Equals(FileVersionInfo.GetVersionInfo(path).OriginalFilename, "dotnet.exe", StringComparison.OrdinalIgnoreCase))
                throw Invalid("WORKER_EXE_GENERIC_HOST_DENIED");
            var digest = await ProductionLocalEnvironment.Sha256FileAsync(path, ct).ConfigureAwait(false);
            if (before != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_CHANGED");
            RequireFinalPath(file.SafeFileHandle, path);
            return new(path, digest, file, parents, before);
        }
        catch { file?.Dispose(); parents.Dispose(); throw; }
    }

    internal sealed class ProcessImageMeasurement(string path, string digest, FileStream file, WorkerKeyNamespace parents, ImageStamp stamp) : IDisposable
    {
        internal string Path { get; } = path;
        internal string Sha256 { get; } = digest;
        internal async Task RequireCurrentAsync(CancellationToken ct)
        {
            if (!string.Equals(CurrentImagePath(), Path, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_IDENTITY_CHANGED");
            RequireEntryBinding(Path, file, Assembly.GetEntryAssembly(), AppContext.BaseDirectory);
            await VerifyFileAsync(ct).ConfigureAwait(false);
            if (!string.Equals(CurrentImagePath(), Path, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_IDENTITY_CHANGED");
            RequireEntryBinding(Path, file, Assembly.GetEntryAssembly(), AppContext.BaseDirectory);
            ct.ThrowIfCancellationRequested();
        }
        internal async Task VerifyFileAsync(CancellationToken ct)
        {
            CanonicalExecutablePath(Path);
            RequireFinalPath(file.SafeFileHandle, Path);
            if (stamp != Stamp(file.SafeFileHandle)
                || await ProductionLocalEnvironment.Sha256FileAsync(Path, ct).ConfigureAwait(false) != Sha256
                || stamp != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_CHANGED");
        }
        public void Dispose() { file.Dispose(); parents.Dispose(); }
    }
    internal readonly record struct ImageStamp(uint Volume, uint IdHigh, uint IdLow, uint SizeHigh, uint SizeLow,
        uint CreatedHigh, uint CreatedLow, uint WrittenHigh, uint WrittenLow);
    private static ImageStamp Stamp(SafeFileHandle handle)
    {
        if (!GetFileInformationByHandle(handle, out var info) || info.Links != 1
            || (info.Attributes & 0x410) != 0 || (info.SizeHigh == 0 && info.SizeLow == 0)
            || (info.IdHigh == 0 && info.IdLow == 0)) throw Invalid("WORKER_EXE_FILE_ID_UNVERIFIED");
        return new(info.Volume, info.IdHigh, info.IdLow, info.SizeHigh, info.SizeLow,
            info.Created.High, info.Created.Low, info.Written.High, info.Written.Low);
    }
    private static void RequireFinalPath(SafeFileHandle handle, string expected)
    {
        var name = new char[32768];
        var length = GetFinalPathNameByHandleW(handle, name, (uint)name.Length, 0);
        if (length == 0 || length >= name.Length) throw Invalid("WORKER_EXE_FINAL_PATH_UNVERIFIED");
        var actual = new string(name, 0, checked((int)length));
        if (!actual.StartsWith(@"\\?\", StringComparison.Ordinal)
            || !string.Equals(actual[4..], expected, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_ALIAS_DENIED");
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeTime { internal uint Low; internal uint High; }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeFileInfo
    {
        internal uint Attributes; internal NativeTime Created; internal NativeTime Accessed; internal NativeTime Written;
        internal uint Volume; internal uint SizeHigh; internal uint SizeLow; internal uint Links; internal uint IdHigh; internal uint IdLow;
    }
#pragma warning disable SYSLIB1054
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, uint flags, [Out] char[] name, ref int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out NativeFileInfo info);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, [Out] char[] name, uint size, uint flags);
#pragma warning restore SYSLIB1054

    private static void RequireCleanJournal(ProductionSubmissionJournal journal, ProductionPlanRecord plan)
    {
        if (journal.Pending().Count != 0 || plan.Tasks.Any(t => journal.Read(plan.ProductionJobId, t.ProductionTaskId) is not null))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
    }
    // Preserve the existing approval authority, but abort if session configuration
    // changes during any of its network awaits, including inside the reused signer.
    internal sealed class SessionBoundApproval(ITrustedReferenceApprovalSource source, Action requireCurrent) : ITrustedReferenceApprovalSource
    {
        public async Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken ct)
        {
            requireCurrent();
            var approved = await source.IsApprovedAsync(descriptor, ct).ConfigureAwait(false);
            requireCurrent();
            return approved;
        }
    }
    private static void ValidateChallenge(JsonElement value, WorkerPublicIdentity identity, string executor, string job, string digest, bool ltx = false)
    {
        Shape(value, "schema_version worker_key_id executor_id production_job_id plan_digest nonce issued_at expires_at");
        if (value.EnumerateObject().Any(p => p.Value.ValueKind != JsonValueKind.String)) throw Invalid("CORE_CHALLENGE_SHAPE_INVALID");
        if (value.GetProperty("schema_version").GetString() != (ltx ? "production.ltx.worker_challenge.v1" : "production.worker_challenge.v1")
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
    // 01. Snapshot consent uses the paired Core transport and existing session
    //     guard. The entire reference, plan digest and intent must agree.
    internal ITrustedReferenceApprovalSource LtxReferenceApproval(
        ProductionReferenceAssetV11Record expected, string planDigest, string vendorIntentDigest) =>
        new SessionBoundApproval(new LtxApproval(this, expected, planDigest, vendorIntentDigest), _requireCurrentSession);

    private sealed class LtxApproval(CoreWorkerChallengeClient client, ProductionReferenceAssetV11Record expected,
        string planDigest, string vendorIntentDigest) : ITrustedReferenceApprovalSource
    {
        public async Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken ct)
        {
            try
            {
                if (expected.RightsScope != "ltx.desktop.local.i2v.production.v1"
                    || descriptor != new TrustedReferenceDescriptor(expected.ApprovalId, expected.ShotId,
                        expected.AssetId, expected.InputRelativePath, expected.Sha256, expected.Bytes))
                    return false;
                var route = "api/v1/production/jobs/" + Uri.EscapeDataString(expected.ProductionJobId) + "/ltx-reference/check";
                using var response = await client.PostAsync(route,
                    new { plan_digest = planDigest, vendor_intent_digest = vendorIntentDigest },
                    HttpStatusCode.OK, ct).ConfigureAwait(false);
                var body = response.RootElement;
                Shape(body, "schema_version plan_digest vendor_intent_digest plan");
                var plan = body.GetProperty("plan");
                var reference = plan.GetProperty("reference_asset").Deserialize<ProductionReferenceAssetV11Record>();
                return body.GetProperty("schema_version").GetString() == "production.ltx.reference_check.v1"
                    && body.GetProperty("plan_digest").GetString() == planDigest
                    && body.GetProperty("vendor_intent_digest").GetString() == vendorIntentDigest
                    && plan.GetProperty("schema_version").GetString() == "1.2"
                    && plan.GetProperty("production_profile").GetString() == "production.ltx.desktop.local.v1"
                    && plan.GetProperty("production_job_id").GetString() == expected.ProductionJobId
                    && plan.GetProperty("production_task_id").GetString() == expected.ProductionTaskId
                    && plan.GetProperty("shot_id").GetString() == expected.ShotId
                    && plan.GetProperty("creative_package_digest").GetString() == expected.CreativePackageDigest
                    && Hash(CanonicalJson.Serialize(JsonNode.Parse(plan.GetRawText())!)) == planDigest
                    && reference == expected;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception) { return false; } // 02. Network loss or changed consent is DENY.
        }
    }

    // 01. Historical frozen plan readback uses the same paired session.
    // 01. Explicit held reservation only, using the already paired Core.
    internal async Task<ProductionJobRecord> FreezeLtxPilotAsync(string packageId, string approvalId,
        string key, CancellationToken ct, string? selectedShotId = null)
    {
        if (!Guid.TryParseExact(packageId, "D", out _) || !Guid.TryParseExact(approvalId, "D", out _)
            || string.IsNullOrWhiteSpace(key) || key.Length > 200
            || (selectedShotId is not null && (selectedShotId.Length is < 1 or > 80
                || selectedShotId.Any(ch => !char.IsAsciiLetterOrDigit(ch) && ch is not ('_' or '.' or '-')))))
            throw Invalid("LTX_FREEZE_REQUEST_INVALID");
        // 02. Keep the old first-shot wire shape unchanged; only full-batch
        //     selection sends the explicit Core-owned shot identity.
        var payload = new JsonObject
        {
            ["creative_package_id"] = packageId,
            ["approved_reference_id"] = approvalId,
            ["idempotency_key"] = key
        };
        if (selectedShotId is not null) payload["selected_shot_id"] = selectedShotId;
        using var result = await PostAsync("api/v1/production/jobs/v1.2/freeze", payload,
            HttpStatusCode.OK, ct).ConfigureAwait(false);
        return result.RootElement.Deserialize<ProductionJobRecord>() ?? throw Invalid("LTX_FREEZE_RECEIPT_INVALID");
    }

    // 01. Read the exact historical candidate receipt through the same
    //     paired Core session. No lease token or GPU operation is involved.
    internal async Task<JsonElement> GetLtxCandidateAsync(string jobId, CancellationToken ct)
    {
        if (!Guid.TryParseExact(jobId, "D", out var parsed) || parsed == Guid.Empty)
            throw Invalid("LTX_CANDIDATE_JOB_INVALID");
        using var result = await RequestAsync(HttpMethod.Get,
            "api/v1/production/jobs/" + Uri.EscapeDataString(jobId) + "/ltx-candidate/result",
            null, HttpStatusCode.OK, ct).ConfigureAwait(false);
        return result.RootElement.Clone();
    }

    internal async Task<JsonElement> GetLtxPlanAsync(string jobId, CancellationToken ct)
    {
        if (!Guid.TryParseExact(jobId, "D", out _)) throw Invalid("LTX_PLAN_JOB_INVALID");
        using var result = await RequestAsync(HttpMethod.Get,
            "api/v1/production/jobs/" + Uri.EscapeDataString(jobId) + "/ltx-plan",
            null, HttpStatusCode.OK, ct).ConfigureAwait(false);
        return result.RootElement.Clone();
    }

    private Task<JsonDocument> PostAsync(string route, object payload, HttpStatusCode expected, CancellationToken ct) =>
        RequestAsync(HttpMethod.Post, route, payload, expected, ct);

    private async Task<JsonDocument> RequestAsync(HttpMethod method, string route, object? payload,
        HttpStatusCode expected, CancellationToken ct)
    {
        _requireCurrentSession();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(10));
        using var request = new HttpRequestMessage(method, route);
        if (payload is not null) request.Content = JsonContent.Create(payload);
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
