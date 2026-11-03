using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>
/// #177 test-only entry hook: a single scoped test Program.cs switch; no shipping changes.
/// Runs ONLY when a separate disposable Windows CI workflow opts in.
/// The actual existing Windows session, DPAPI signer, snapshots and Core client
/// exchange HTTP with the real, unmodified Python FastAPI production router.
/// </summary>
internal static class RealPythonCoreInteropTests
{
    private const string Executor = "windows-same-exe-worker";
    private static readonly byte[] Png = Convert.FromBase64String(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=");

    internal static async Task RunAsync(string mode)
    {
        // ── A normal, awaited test-entry call, not a blocking module initializer.
        // ── This prevents CLI bootstrap and async session initialization deadlocks.
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true"
            || Environment.GetEnvironmentVariable("P0_REAL_CORE_LOCALHOST_CI_ONLY") != "1")
            throw new InvalidOperationException("REAL_CORE_INTEROP_REQUIRES_EPHEMERAL_WINDOWS_CI");
        var root = Environment.GetEnvironmentVariable("P0_REAL_CORE_INTEROP_ROOT")
            ?? throw new InvalidOperationException("REAL_CORE_TEMP_ROOT_REQUIRED");
        if (!Path.IsPathFullyQualified(root) || !Path.GetFileName(Path.TrimEndingDirectorySeparator(root))
            .StartsWith("p0-real-core-interop-", StringComparison.Ordinal))
            throw new InvalidOperationException("REAL_CORE_TEMP_ROOT_INVALID");
        var keyRoot = Path.Combine(root, "dpapi-key");
        if (mode == "seed-key")
        {
            // ── The production DPAPI factory must exclusively create this
            // ── directory with owner-only ACLs; pre-creating it is forbidden.
            var identity = ProtectedWorkerSigningKey.Create(keyRoot, Executor);
            // ── Public key and fingerprint ONLY, never DPAPI seed or bearer.
            File.WriteAllText(Path.Combine(root, "identity-public.json"), JsonSerializer.Serialize(new
            {
                key_id = identity.KeyId,
                fingerprint = identity.Fingerprint,
                public_key_hex = identity.PublicKeyHex,
            }));
            Console.WriteLine("REAL_WINDOWS_DPAPI_KEY=TEST_ONLY; PUBLIC_PIN=READY");
            return;
        }

        Console.WriteLine("REAL_WINDOWS_PHASE=MANIFEST_BEGIN");
        var manifest = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, "interop-fixture-public.json")));
        using (manifest)
        {
            var job = manifest.RootElement.GetProperty("job_id").GetString()!;
            var digest = manifest.RootElement.GetProperty("plan_digest").GetString()!;
            var keyId = manifest.RootElement.GetProperty("key_id").GetString()!;
            var bearer = Environment.GetEnvironmentVariable("P0_CORE_INTEROP_BEARER")
                ?? throw new InvalidOperationException("INTEROP_BEARER_MISSING");
            var uri = Environment.GetEnvironmentVariable("P0_REAL_CORE_URL")
                ?? throw new InvalidOperationException("INTEROP_LOCALHOST_URL_MISSING");
            var baseUri = new Uri(uri, UriKind.Absolute);
            if (baseUri.Host != "127.0.0.1" || baseUri.AbsolutePath != "/" || baseUri.Scheme != "http")
                throw new InvalidOperationException("REAL_CORE_NOT_LOOPBACK");

            using var http = new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false })
                { BaseAddress = baseUri, Timeout = TimeSpan.FromSeconds(15) };
            http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", bearer);
            var route = "api/v1/production/jobs/" + Uri.EscapeDataString(job);
            var exact = new { worker_key_id = keyId, executor_id = Executor, plan_digest = digest };
            if (mode == "pilot-after-revoke")
            {
                using var leaseDoc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, "pilot-lease-ci-only.json")));
                var authority = new { executor_id = Executor, lease_token = leaseDoc.RootElement.GetProperty("lease_token").GetString() };
                using var heartbeat = await http.PostAsJsonAsync(route + "/heartbeat", authority);
                Check(heartbeat.StatusCode == HttpStatusCode.Conflict, "B_REVOKED_LEASE_HEARTBEAT_DENIED");
                var taskId = leaseDoc.RootElement.GetProperty("task_id").GetString();
                using var attempt = await http.PostAsJsonAsync(route + "/tasks/" + taskId + "/attempt",
                    new { authority.executor_id, authority.lease_token, comfy_prompt_id = (string?)null });
                Check(attempt.StatusCode == HttpStatusCode.Conflict, "B_REVOKED_LEASE_ATTEMPT_DENIED");
                Console.WriteLine("REAL_B_REVOKED_AFTER_CLAIM=DENIED; ATTEMPT=0; COMFY_POST=0");
                return;
            }
            if (mode == "negatives")
            {
                // ── True real-Core network errors, not .NET fake HTTP responses.
                using var unauthorized = new HttpClient { BaseAddress = baseUri, Timeout = TimeSpan.FromSeconds(10) };
                using var unauthorizedResponse = await unauthorized.PostAsJsonAsync(route + "/worker-challenge", exact);
                Check(unauthorizedResponse.StatusCode == HttpStatusCode.Unauthorized, "HTTP_BEARER_401");
                foreach (var wrong in new object[]
                {
                    new { worker_key_id = "wk-" + new string('f', 40), executor_id = Executor, plan_digest = digest },
                    new { worker_key_id = keyId, executor_id = "wrong-executor", plan_digest = digest },
                    new { worker_key_id = keyId, executor_id = Executor, plan_digest = new string('b', 64) },
                })
                {
                    using var denied = await http.PostAsJsonAsync(route + "/worker-challenge", wrong);
                    await ExactErrorAsync(denied, HttpStatusCode.Conflict, "PRODUCTION_V11_CHALLENGE_UNAVAILABLE");
                }
                using var retry = await http.PostAsJsonAsync(route + "/worker-challenge", exact);
                await ExactErrorAsync(retry, HttpStatusCode.Conflict, "PRODUCTION_V11_CHALLENGE_UNAVAILABLE");
                using var fakeEnroll = await http.PostAsJsonAsync("api/v1/production/worker-keys/register", exact);
                Check(fakeEnroll.StatusCode == HttpStatusCode.NotFound, "NO_BEARER_KEY_ENROLL");
                using var claim = await http.PostAsJsonAsync(route + "/claim", new { executor_id = Executor });
                await ExactErrorAsync(claim, HttpStatusCode.Conflict, "PRODUCTION_V11_WORKER_ADAPTER_REQUIRED");
                Console.WriteLine("REAL_PYTHON_CORE_HTTP_NEGATIVES=PASS; 401=PASS; KEY_EXECUTOR_PLAN=409; CLAIM=BLOCKED");
                return;
            }
            if (mode == "reissue")
            {
                using var response = await http.PostAsJsonAsync(route + "/worker-challenge", exact);
                Check(response.StatusCode == HttpStatusCode.OK, "EXPIRED_NONCE_REISSUE");
                var data = await response.Content.ReadFromJsonAsync<JsonElement>();
                Check(data.GetProperty("schema_version").GetString() == "production.worker_challenge.v1", "REAL_CHALLENGE_SCHEMA");
                Check(data.GetProperty("nonce").GetString() is { Length: 64 }, "REAL_CHALLENGE_RANDOM_NONCE");
                Console.WriteLine("REAL_CORE_EXPIRED_OLD_NONCE=PASS; FRESH_CHALLENGE_REISSUED=PASS");
                return;
            }
            if (mode == "after-revoke")
            {
                using var response = await http.PostAsJsonAsync(route + "/worker-challenge", exact);
                await ExactErrorAsync(response, HttpStatusCode.Conflict, "PRODUCTION_V11_CHALLENGE_UNAVAILABLE");
                Console.WriteLine("REAL_CORE_REVOKED_BETWEEN_CHALLENGE_AND_SIGNING=DENIED");
                return;
            }
            if (mode is not ("run" or "pilot")) throw new InvalidOperationException("UNKNOWN_CI_ONLY_MODE");

            var input = Path.Combine(root, "windows-input");
            var tokenStore = new CredentialManagerTokenStore("PicotooPet.CI.RealCore/" + Guid.NewGuid().ToString("N"));
            Console.WriteLine("REAL_WINDOWS_PHASE=SESSION_CONSTRUCT");
            await using var session = new ControlCenterSession(
                tokenStore,
                new DesktopSettingsStore(Path.Combine(root, "desktop-settings.json")),
                new SafeFileLogger(Path.Combine(root, "interop-client.log")),
                new ConnectionStateStore(), new CapabilityStateStore(), new TaskStateStore());
            // ── Using genuine ControlCenterSession endpoints and Credential
            // ── Manager token store, not a mocked production session.
            try
            {
                // ── CI-only endpoint configuration avoids startup health /
                // ── event-stream pairing unrelated to the frozen production
                // ── router. Credential Manager and every production HTTP
                // ── transport/approval/signing implementation stay genuine.
                var endpoint = typeof(ControlCenterSession).GetField(
                    "_macBaseUrl", BindingFlags.Instance | BindingFlags.NonPublic)
                    ?? throw new InvalidOperationException("CI_ENDPOINT_FIELD_NOT_FOUND");
                endpoint.SetValue(session, uri);
                tokenStore.Save(bearer);
                Console.WriteLine("REAL_WINDOWS_PHASE=FETCH_REAL_PLAN");
                using var readBudget = new CancellationTokenSource(TimeSpan.FromSeconds(12));
                var plan = await session.GetProductionPlanAsync(job, readBudget.Token).WaitAsync(TimeSpan.FromSeconds(14));
                Console.WriteLine("REAL_WINDOWS_PHASE=REAL_PLAN_RECEIVED");
                Check(plan.SchemaVersion == "1.1" && plan.Tasks.Length == 1
                    && plan.Tasks[0].ReferenceAsset is not null, "REAL_CORE_FROZEN_PLAN");
                Check(plan.ProductionJobId == job, "REAL_CORE_JOB_ID");
                Directory.CreateDirectory(input);
                var reference = plan.Tasks[0].ReferenceAsset!;
                var original = Path.Combine(input, reference.InputRelativePath.Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(original)!);
                File.WriteAllBytes(original, Png);
                Check(SHA256.HashData(Png).SequenceEqual(Convert.FromHexString(reference.Sha256))
                    && Png.Length == reference.Bytes, "REAL_CORE_APPROVAL_MATCHES_DISK_BYTES");
                var journal = new ProductionSubmissionJournal(Path.Combine(root, "windows-journal"));
                var publicPin = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root, "identity-public.json")));
                using (publicPin)
                {
                    using var comfySentinel = new TcpListener(IPAddress.Loopback, 8188);
                    comfySentinel.Start();
                    Console.WriteLine("REAL_WINDOWS_PHASE=WORKER_CLIENT_START");
                    using var client = session.CreateWorkerChallengePreflightClient();
                    if (mode == "pilot")
                    {
                        Check(Environment.GetEnvironmentVariable("P0_OPERATOR_TRUSTED_PILOT_CI_ONLY") == "1", "B_FIXTURE_EXPLICIT_POLICY");
                        var snapshots = new List<DurableReferenceSnapshot>();
                        try
                        {
                            using var gpu = journal.AcquireGpu();
                            var store = new ProductionReferenceSnapshotStore(input, (p, t, d) =>
                                new CoreReferenceApprovalSource(session, p.ProductionJobId, t.ProductionTaskId, d));
                            var graphs = plan.Tasks.ToDictionary(t => t.ProductionTaskId, _ => new string('e', 64));
                            foreach (var task in plan.Tasks)
                                snapshots.Add(await store.PrepareAsync(plan, task, digest, graphs[task.ProductionTaskId], journal, CancellationToken.None));
                            var admitted = await client.ClaimPreparedAsync(plan, keyRoot, Executor,
                                publicPin.RootElement.GetProperty("fingerprint").GetString()!, snapshots, graphs, journal, gpu,
                                CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(40));
                            Check(admitted.ProductionJobId == job && admitted.Plan.SchemaVersion == "1.1"
                                && admitted.ExecutorId == Executor && !string.IsNullOrWhiteSpace(admitted.LeaseToken), "B_REAL_CLAIM_RESPONSE");
                            File.WriteAllText(Path.Combine(root, "pilot-lease-ci-only.json"), JsonSerializer.Serialize(new {
                                lease_token = admitted.LeaseToken, task_id = plan.Tasks[0].ProductionTaskId }));
                            var wire = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "windows-witness-public.json")));
                            using var replay = await http.PostAsJsonAsync(route + "/claim", new { executor_id = Executor, worker_witness = wire });
                            Check(replay.StatusCode == HttpStatusCode.Conflict, "B_SIGNED_CLAIM_REPLAY_DENIED");
                            Check(journal.Pending().Count == 0 && !comfySentinel.Pending(), "B_CLAIM_NEVER_POSTS_COMFY");
                            Console.WriteLine("REAL_B_WINDOWS_DPAPI_FASTAPI_CLAIM=PASS; REPLAY=409; TRUST=OPERATOR_PRIVATE_HOST; HARDWARE_ATTESTATION=NO; COMFY_POST=0");
                        }
                        finally { for (var i = snapshots.Count - 1; i >= 0; i--) snapshots[i].Dispose(); }
                        return;
                    }
                    var result = await client.RunExpectedDenyAsync(
                        plan, input, keyRoot, Executor,
                        publicPin.RootElement.GetProperty("fingerprint").GetString()!,
                        plan.Tasks.ToDictionary(t => t.ProductionTaskId, _ => new string('e', 64)),
                        journal, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(40));
                    Console.WriteLine("REAL_WINDOWS_PHASE=CORE_EXPECTED_DENIAL_RECEIVED");
                    Check(result == "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED", "REAL_CORE_EXPECTED_409");
                    Check(!comfySentinel.Pending(), "COMFY_NETWORK_REQUEST_ZERO");
                    Check(journal.Pending().Count == 0, "COMFY_JOURNAL_ZERO");
                    // Probe immediately while the original signer phase and
                    // Comfy sentinel are active; do not spend the 30s lifetime
                    // on another process/EXE measurement before these checks.
                    await SignedWireNegativesAsync(http, route, root);
                    Check(!comfySentinel.Pending(), "SIGNED_WIRE_COMFY_ZERO");
                    // #152: a real, durable unresolved local intent must stop
                    // the existing client BEFORE another challenge or signature.
                    // Preserve it; never clear it as a way to regain admission.
                    var oldJournal = new ProductionSubmissionJournal(Path.Combine(root, "old-windows-journal"));
                    var oldIntent = new ProductionSubmission(job, plan.Tasks[0].ProductionTaskId,
                        digest, new string('e', 64), "Submitting", null);
                    oldJournal.Save(oldIntent);
                    try
                    {
                        await client.RunExpectedDenyAsync(plan, input, keyRoot, Executor,
                            publicPin.RootElement.GetProperty("fingerprint").GetString()!,
                            plan.Tasks.ToDictionary(t => t.ProductionTaskId, _ => new string('e', 64)),
                            oldJournal, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));
                        throw new InvalidOperationException("OLD_JOURNAL_MUST_DENY");
                    }
                    catch (ProductionWorkerException error) when (error.Code == "MEDIA_PENDING_RECONCILIATION") { }
                    Check(oldJournal.Read(job, plan.Tasks[0].ProductionTaskId) == oldIntent, "OLD_JOURNAL_PRESERVED");
                    Check(!comfySentinel.Pending(), "OLD_JOURNAL_COMFY_ZERO");
                    Console.WriteLine("REAL_WINDOWS_OLD_JOURNAL=DENIED_BEFORE_CHALLENGE; INTENT=PRESERVED; COMFY_POST=0");
                }
                Console.WriteLine("REAL_MAC_CORE_FASTAPI_WIN_DPAPI_ED25519_HTTP=PASS; PREFLIGHT=409; COMFY_POST=0");
            }
            finally
            {
                Console.WriteLine("REAL_WINDOWS_PHASE=SESSION_FINALLY");
                tokenStore.Delete();
            }
        }
    }

    private static async Task ExactErrorAsync(HttpResponseMessage response,
        HttpStatusCode expected, string code)
    {
        Check(response.StatusCode == expected, "EXPECTED_HTTP_STATUS_" + code);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Check(body.RootElement.GetProperty("error").GetProperty("code").GetString() == code,
            "EXPECTED_ERROR_" + code);
    }

    private static async Task SignedWireNegativesAsync(HttpClient http, string route, string root)
    {
        var wire = File.ReadAllText(Path.Combine(root, "windows-witness-public.json"));
        var witness = JsonNode.Parse(wire)!.AsObject();
        var signature = Convert.FromHexString(witness["signature"]!.GetValue<string>());
        signature[0] ^= 1;
        witness["signature"] = Convert.ToHexStringLower(signature);
        using (var bad = await http.PostAsJsonAsync(route + "/witness/preflight", witness))
            await ExactErrorAsync(bad, HttpStatusCode.Conflict, "PRODUCTION_V11_WORKER_SIGNATURE_INVALID");
        await Task.WhenAll(Enumerable.Range(0, 3).Select(async _ =>
        {
            using var replay = await http.PostAsJsonAsync(route + "/witness/preflight", JsonNode.Parse(wire));
            await ExactErrorAsync(replay, HttpStatusCode.Conflict, "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED");
        }));
        // Hostile altered declarations, not newly signed honest measurements.
        // Exact early Journal errors demonstrate rejection before verification.
        foreach (var (state, code) in new[] {
            ("UNCERTAIN", "PRODUCTION_V11_WITNESS_POST_UNCERTAIN"),
            ("BOUND_RECOVERY", "PRODUCTION_V11_WITNESS_JOURNAL_MISMATCH") })
        {
            witness = JsonNode.Parse(wire)!.AsObject();
            witness["journal_state"] = state;
            using var denied = await http.PostAsJsonAsync(route + "/witness/preflight", witness);
            await ExactErrorAsync(denied, HttpStatusCode.Conflict, code);
        }
        Console.WriteLine("REAL_WINDOWS_WIRE_NEGATIVES=PASS; BAD_SIGNATURE=409; CONCURRENT_REPLAY=409; JOURNAL=409");
    }

    private static void Check(bool accepted, string reason)
    {
        if (!accepted) throw new InvalidOperationException("P0_REAL_CORE_INTEROP_" + reason);
    }
}
