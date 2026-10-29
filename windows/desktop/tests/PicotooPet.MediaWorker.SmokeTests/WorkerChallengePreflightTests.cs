using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Math.EC.Rfc8032;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class WorkerChallengePreflightTests
{
    private const string Executor = "windows-same-exe-worker";
    private const string Token = "offline-challenge-transport-only";
    public static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows() || Environment.GetEnvironmentVariable("CI") != "true")
            throw new InvalidOperationException("CHALLENGE_REQUIRES_DISPOSABLE_WINDOWS_CI");
        await using var comfy = new Server(null, 8188);
        await using (var f = await Fixture.CreateAsync())
        {
            using (var client = f.Session.CreateWorkerChallengePreflightClient())
                RecoveryTests.Assert(await f.RunAsync(client) == "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED", "409 is expected denial only");
            RecoveryTests.Assert(f.Core.Witnesses == 1 && f.Core.ValidSignatures == 1, "real DPAPI key signed the Core nonce and exact measured bytes");
            // Fresh client and reopened DPAPI identity cannot retry the burned nonce.
            using (var restarted = f.Session.CreateWorkerChallengePreflightClient()) await DeniedAsync(() => f.RunAsync(restarted));
            RecoveryTests.Assert(f.Core.Witnesses == 1, "restart/replay emits no second witness");
            await RecoveryTests.ThrowsCodeAsync("I2V_CROSS_ENDPOINT_WORKER_PROOF_REQUIRED", () =>
            {
                new ShippingReferenceComposition(f.Session, Executor).RequireVerifiedWorkerProof(f.Work.Plan);
                return Task.CompletedTask;
            });
            f.AssertSafe();
        }
        foreach (var mode in new[] { "executor", "job", "key", "digest", "schema", "nonce", "nonce-type", "missing", "session-changed", "session-during-sign", "expired", "future", "long-window", "offset", "extra", "duplicate", "oversize", "redirect", "challenge-401", "approval-revoked", "journal-during-challenge", "key-pin", "reparse", "snapshot-tamper" })
        {
            await using var f = await Fixture.CreateAsync();
            f.Core.Mode = mode;
            if (mode == "reparse")
            {
                var original = f.Work.Full(f.Work.Reference.InputRelativePath);
                var outside = Path.Combine(f.Work.Root, "outside.png");
                File.Move(original, outside); File.CreateSymbolicLink(original, outside);
            }
            if (mode == "snapshot-tamper")
            {
                using var snapshot = await f.Work.PrepareAsync();
                // A forged pre-existing receipt is denied rather than recreated.
                var receipt = f.Work.Full(snapshot.RelativePath) + ".snapshot.json";
                var info = new FileInfo(receipt);
                var acl = info.GetAccessControl();
                foreach (System.Security.AccessControl.FileSystemAccessRule rule in acl.GetAccessRules(true, false, typeof(System.Security.Principal.SecurityIdentifier)))
                    if (rule.AccessControlType == System.Security.AccessControl.AccessControlType.Deny) acl.RemoveAccessRuleSpecific(rule);
                info.SetAccessControl(acl);
                // Release verifier pins before tampering to simulate a prior process.
                snapshot.Dispose(); File.WriteAllText(receipt, "{}");
            }
            using var client = f.Session.CreateWorkerChallengePreflightClient();
            var failure = await DeniedAsync(() => f.RunAsync(client, mode == "key-pin" ? new string('f', 64) : null));
            RecoveryTests.Assert(f.Core.Challenges == (mode == "key-pin" ? 0 : 1), "one exact challenge or local pin rejection");
            if (mode is "executor" or "job" or "key" or "digest" or "schema" or "nonce" or "nonce-type" or "missing" or "expired" or "future" or "long-window" or "offset" or "extra" or "duplicate" or "oversize" or "redirect" or "challenge-401")
                RecoveryTests.Assert(failure is InvalidDataException, mode + " must fail explicit response validation, not a network error");
            RecoveryTests.Assert(f.Core.Witnesses == 0 && !Directory.EnumerateFiles(f.KeyRoot, "used-*").Any(), mode + " must fail before signing/transmission");
            if (mode == "session-during-sign") RecoveryTests.Assert(f.Core.AuthorizationReads == 7, "session changed during signer approval, after six snapshot checks");
            f.AssertSafe();
            Console.WriteLine("P0_CORE_CHALLENGE_NEGATIVE=" + mode + "; WITNESS=0; COMFY_POST=0");
        }
        foreach (var phase in new[] { "Prepared", "Submitting", "Settled" })
        {
            await using var f = await Fixture.CreateAsync();
            var prior = new ProductionSubmission("job", "task", f.Work.Digest, new string('e', 64), phase, null);
            f.Work.Journal.Save(prior);
            using var client = f.Session.CreateWorkerChallengePreflightClient();
            await DeniedAsync(() => f.RunAsync(client));
            RecoveryTests.Assert(f.Core.Challenges == 0 && f.Core.Witnesses == 0 && f.Work.Journal.Read("job", "task") == prior, "old journal blocks before challenge and remains unchanged");
            f.AssertSafe();
        }
        foreach (var mode in new[] { "preflight-200", "preflight-204", "preflight-unknown-409", "preflight-redirect", "preflight-timeout" })
        {
            await using var f = await Fixture.CreateAsync(); f.Core.Mode = mode;
            using var client = f.Session.CreateWorkerChallengePreflightClient();
            await DeniedAsync(() => f.RunAsync(client));
            RecoveryTests.Assert(f.Core.Witnesses == 1 && f.Core.ValidSignatures == 1, "only one signed preflight; no retry on uncertainty");
            using var restart = f.Session.CreateWorkerChallengePreflightClient();
            f.Core.Mode = "normal";
            await DeniedAsync(() => f.RunAsync(restart));
            RecoveryTests.Assert(f.Core.Witnesses == 1, "uncertain response never reuses signed nonce");
            f.AssertSafe();
        }
        foreach (var cancel in new[] { false, true })
        {
            await using var f = await Fixture.CreateAsync(); f.Core.Mode = "challenge-timeout";
            using var client = f.Session.CreateWorkerChallengePreflightClient();
            using var ct = new CancellationTokenSource(); if (cancel) ct.CancelAfter(TimeSpan.FromMilliseconds(150));
            var watch = Stopwatch.StartNew();
            await DeniedAsync(() => f.RunAsync(client, ct: ct.Token));
            RecoveryTests.Assert(watch.Elapsed < TimeSpan.FromSeconds(20) && f.Core.Witnesses == 0 && !Directory.EnumerateFiles(f.KeyRoot, "used-*").Any(), "bounded timeout/cancellation before signing");
            f.AssertSafe();
        }
        RecoveryTests.Assert(comfy.Requests.IsEmpty, "all preflight cases must issue zero Comfy requests");
        Console.WriteLine("P0_CORE_CHALLENGE_EXPECTED_409=PASS; REAL_ED25519=PASS; COMFY_POSTS=0; CLAIM=0; ATTEMPT=0; I2V=BLOCKED");
    }

    private static async Task<Exception> DeniedAsync(Func<Task<string>> operation)
    {
        try { await operation(); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or CryptographicException or ProductionWorkerException or HttpRequestException or OperationCanceledException or JsonException) { return e; }
        throw new InvalidOperationException("preflight must deny");
    }

    private sealed class Fixture : IAsyncDisposable
    {
        internal DurableReferenceSnapshotTests.Fixture Work { get; } = new();
        internal string KeyRoot => Path.Combine(Work.Root, "challenge-key");
        internal WorkerPublicIdentity Identity { get; }
        internal Server Core { get; }
        internal ControlCenterSession Session { get; }
        private readonly CredentialManagerTokenStore _tokens = new("PicotooPet.CI.WorkerChallenge/" + Guid.NewGuid().ToString("N"));
        private Fixture()
        {
            Identity = ProtectedWorkerSigningKey.Create(KeyRoot, Executor);
            Core = new(this);
            Session = new(_tokens, new(Path.Combine(Work.Root, "settings.json")), new SafeFileLogger(Path.Combine(Work.Root, "test.log")),
                new ConnectionStateStore(), new CapabilityStateStore(), new TaskStateStore());
        }
        internal static async Task<Fixture> CreateAsync()
        {
            var f = new Fixture();
            try
            {
                await new DesktopSettingsStore(Path.Combine(f.Work.Root, "settings.json")).SaveAsync(new(f.Core.Url), CancellationToken.None);
                await f.Session.InitializeAsync(CancellationToken.None);
                f._tokens.Save(Token);
                return f;
            }
            catch { await f.DisposeAsync(); throw; }
        }
        internal Task<string> RunAsync(CoreWorkerChallengeClient client, string? pin = null, CancellationToken ct = default) =>
            client.RunExpectedDenyAsync(Work.Plan, Work.Root, KeyRoot, Executor, pin ?? Identity.Fingerprint,
                new Dictionary<string, string> { [Work.Task.ProductionTaskId] = new('e', 64) }, Work.Journal, ct);
        internal void ChangeTransportToken() => _tokens.Save("changed-transport-only");
        internal void AssertSafe() => RecoveryTests.Assert(Core.Requests.All(r => r.StartsWith("GET ", StringComparison.Ordinal)
            || r == "POST /api/v1/production/jobs/job/worker-challenge" || r == "POST /api/v1/production/jobs/job/witness/preflight"), "no claim, attempt, enrollment or Comfy path");
        public async ValueTask DisposeAsync() { await Session.DisposeAsync(); _tokens.Delete(); await Core.DisposeAsync(); Work.Dispose(); }
    }

    private sealed class Server : IAsyncDisposable
    {
        private readonly Fixture? _f;
        private readonly HttpListener _listener = new();
        private readonly CancellationTokenSource _stop = new();
        private readonly Task _loop;
        internal string Url { get; }
        internal string Mode { get; set; } = "normal";
        internal int Witnesses { get; private set; }
        internal int ValidSignatures { get; private set; }
        internal int Challenges { get; private set; }
        internal int AuthorizationReads { get; private set; }
        internal ConcurrentQueue<string> Requests { get; } = new();
        internal Server(Fixture? f, int port = 0)
        {
            _f = f;
            var reservation = new TcpListener(IPAddress.Loopback, port); reservation.Start();
            var actual = ((IPEndPoint)reservation.LocalEndpoint).Port; reservation.Stop();
            Url = "http://127.0.0.1:" + actual.ToString(System.Globalization.CultureInfo.InvariantCulture) + "/";
            _listener.IgnoreWriteExceptions = true;
            _listener.Prefixes.Add(Url); _listener.Start(); _loop = ServeAsync();
        }
        private async Task ServeAsync()
        {
            try
            {
                while (!_stop.IsCancellationRequested)
                {
                    var c = await _listener.GetContextAsync();
                    var path = c.Request.Url!.AbsolutePath;
                    var mode = Mode;
                    Requests.Enqueue(c.Request.HttpMethod + " " + path);
                    object? body = null; string? raw = null; var status = 200;
                    if (_f is null || c.Request.Headers["Authorization"] != "Bearer " + Token) status = 403;
                    else if (c.Request.HttpMethod == "POST" && path.EndsWith("/worker-challenge", StringComparison.Ordinal))
                    {
                        Challenges++;
                        using var request = await JsonDocument.ParseAsync(c.Request.InputStream);
                        var data = request.RootElement;
                        RecoveryTests.Assert(data.EnumerateObject().Count() == 3 && data.GetProperty("worker_key_id").GetString() == _f.Identity.KeyId
                            && data.GetProperty("executor_id").GetString() == Executor && data.GetProperty("plan_digest").GetString() == _f.Work.Digest, "exact challenge request; no caller public key/enrollment flag");
                        var now = DateTimeOffset.UtcNow;
                        var challenge = JsonSerializer.SerializeToNode(new { schema_version = "production.worker_challenge.v1", worker_key_id = _f.Identity.KeyId,
                            executor_id = Executor, production_job_id = "job", plan_digest = _f.Work.Digest, nonce = new string('2', 64),
                            issued_at = Stamp(now), expires_at = Stamp(now.AddSeconds(28)) })!;
                        switch (mode)
                        {
                            case "executor": challenge["executor_id"] = "other"; break;
                            case "job": challenge["production_job_id"] = "other"; break;
                            case "key": challenge["worker_key_id"] = "wk-" + new string('a', 40); break;
                            case "digest": challenge["plan_digest"] = new string('a', 64); break;
                            case "schema": challenge["schema_version"] = "production.worker_challenge.v2"; break;
                            case "nonce": challenge["nonce"] = new string('0', 64); break;
                            case "nonce-type": challenge["nonce"] = 123; break;
                            case "missing": challenge.AsObject().Remove("issued_at"); break;
                            case "session-changed": _f.ChangeTransportToken(); break;
                            case "expired": challenge["issued_at"] = Stamp(now.AddSeconds(-31)); challenge["expires_at"] = Stamp(now.AddSeconds(-1)); break;
                            case "future": challenge["issued_at"] = Stamp(now.AddSeconds(10)); challenge["expires_at"] = Stamp(now.AddSeconds(30)); break;
                            case "long-window": challenge["expires_at"] = Stamp(now.AddSeconds(31)); break;
                            case "offset": challenge["issued_at"] = now.ToOffset(TimeSpan.FromHours(1)).ToString("O", System.Globalization.CultureInfo.InvariantCulture); break;
                            case "extra": challenge["authorized"] = true; break;
                            case "duplicate": raw = challenge.ToJsonString().Replace("{", "{\"nonce\":\"" + new string('a', 64) + "\",", StringComparison.Ordinal); break;
                            case "oversize": raw = new string(' ', 17000) + challenge.ToJsonString(); break;
                            case "redirect": status = 307; c.Response.RedirectLocation = Url + "prompt"; break;
                            case "challenge-401": status = 401; break;
                            case "approval-revoked": _f.Work.Approved = false; break;
                            case "journal-during-challenge": _f.Work.Journal.Save(new("job", "task", _f.Work.Digest, new string('e', 64), "Submitting", null)); break;
                            case "challenge-timeout": await Task.Delay(TimeSpan.FromSeconds(12), _stop.Token); break;
                        }
                        body = challenge;
                    }
                    else if (c.Request.HttpMethod == "POST" && path.EndsWith("/witness/preflight", StringComparison.Ordinal))
                    {
                        Witnesses++;
                        using var request = await JsonDocument.ParseAsync(c.Request.InputStream);
                        var witness = request.RootElement; var payload = WorkerWitnessEncoding.Payload(witness);
                        if (Ed25519.Verify(Convert.FromHexString(witness.GetProperty("signature").GetString()!), 0,
                            Convert.FromHexString(_f.Identity.PublicKeyHex), 0, payload, 0, payload.Length)) ValidSignatures++;
                        var code = mode == "preflight-unknown-409" ? "OTHER" : "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED";
                        status = mode switch { "preflight-200" => 200, "preflight-204" => 204, "preflight-redirect" => 307, _ => 409 };
                        if (status == 307) c.Response.RedirectLocation = Url + "prompt";
                        if (mode == "preflight-timeout") await Task.Delay(TimeSpan.FromSeconds(12), _stop.Token);
                        body = new { error = new { code, message = "fixture denial", retryable = false, trace_id = "fixture" } };
                    }
                    else if (c.Request.HttpMethod == "GET" && path == "/api/v1/production/jobs/job/plan") body = _f.Work.Plan;
                    else if (c.Request.HttpMethod == "GET" && path == "/api/v1/production/jobs/job") body = new ProductionJobRecord("job", "creative",
                        _f.Work.Plan.CreativePackageDigest, _f.Work.Plan.ProjectKey, _f.Work.Plan.ProductionProfile, _f.Work.Digest,
                        "Ready", null, null, null, null, "fixture", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
                    else if (c.Request.HttpMethod == "GET" && path.EndsWith("/reference-authorization", StringComparison.Ordinal) && _f.Work.Approved)
                    {
                        AuthorizationReads++;
                        if (mode == "session-during-sign" && AuthorizationReads == 7) _f.ChangeTransportToken();
                        var r = _f.Work.Reference;
                        body = new ProductionReferenceAuthorizationV11Record("reference_authorization.v1", "job", "task", _f.Work.Digest,
                            new(r.ApprovalId, r.ShotId, r.AssetId, r.InputRelativePath, r.Sha256, r.Bytes), r);
                    }
                    else status = 409;
                    c.Response.StatusCode = status; c.Response.ContentType = "application/json";
                    var bytes = status == 204 ? [] : raw is null ? JsonSerializer.SerializeToUtf8Bytes(body) : System.Text.Encoding.UTF8.GetBytes(raw);
                    c.Response.ContentLength64 = bytes.Length;
                    try { await c.Response.OutputStream.WriteAsync(bytes); c.Response.Close(); }
                    catch (Exception e) when (mode.EndsWith("timeout", StringComparison.Ordinal) && e is IOException or HttpListenerException) { c.Response.Abort(); }
                }
            }
            catch (OperationCanceledException) when (_stop.IsCancellationRequested) { }
            catch (HttpListenerException) when (_stop.IsCancellationRequested) { }
            catch (ObjectDisposedException) when (_stop.IsCancellationRequested) { }
        }
        public async ValueTask DisposeAsync() { await _stop.CancelAsync(); _listener.Stop(); await _loop; _listener.Close(); _stop.Dispose(); }
        private static string Stamp(DateTimeOffset value) => value.ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'", System.Globalization.CultureInfo.InvariantCulture);
    }
}
