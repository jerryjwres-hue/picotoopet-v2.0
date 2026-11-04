param([Parameter(Mandatory)][string]$RepoRoot)
$ErrorActionPreference = 'Stop'
$source = Get-Content (Join-Path $RepoRoot 'windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs') -Raw
$marker = 'internal sealed class DiagnosticFailureContext'
if (-not $source.Contains($marker)) { throw 'DIAGNOSTIC_FAILURE_CONTEXT_MISSING' }
$contextSource = $source.Substring($source.IndexOf($marker, [StringComparison]::Ordinal))
$apiSource = Get-Content (Join-Path $RepoRoot 'windows/desktop/src/PicotooPet.Desktop.Core/Networking/ApiException.cs') -Raw
$apiSource = $apiSource.Replace('namespace PicotooPet.Desktop.Core.Networking;', '')
$usings = @'
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Networking;
'@
$fixture = @'
public static class FailureContextNegativeFixture {
    public static async Task Run() {
        // ── Only loopback GET is used; no credential store, Core, task or GPU access.
        var root = Path.Combine(Path.GetTempPath(), "diagnostic-context-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var secret = "SENTINEL_TOKEN_NEVER_EMIT_987654";
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        HttpRequestException socketFailure;
        using (var client = new HttpClient(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(3) }) {
            try { using var response = await client.GetAsync($"http://127.0.0.1:{port}/api/v1/health"); throw new Exception("Expected refused socket"); }
            catch (HttpRequestException error) { socketFailure = error; }
        }
        var context = new DiagnosticFailureContext(new Uri($"http://proxy-user:{secret}@127.0.0.1:{port}/private?credential={secret}"));
        context.SetCredentialToken(secret);
        context.EnterStage("rest_health", 0);
        context.RecordHealth(); context.RecordHealth();
        context.EnterStage("websocket_connect");
        context.EnterStage("cpu_task_submit", 0);
        var taskId = "11111111-2222-3333-4444-555555555555";
        context.RecordTaskSubmitted(taskId);
        context.RecordPing();
        context.EnterStage("cpu_task_event_wait", 0);
        await context.TryWriteAsync(Path.Combine(root, "report.json"), new ApiException(
            "NETWORK_ERROR", "Bearer " + secret, true, "0123456789abcdef0123456789abcdef", 0, socketFailure));
        var path = Directory.GetFiles(root, "*.failure-context.*.json").Single();
        var text = File.ReadAllText(path);
        Require(!text.Contains(secret) && !text.Contains("proxy-user") && !text.Contains("Bearer") && !text.Contains("private?"), "secret leaked");
        using (var doc = JsonDocument.Parse(text)) {
            var data = doc.RootElement;
            Require(data.GetProperty("schema_version").GetString() == "diagnostic_failure_context.v1", "schema");
            Require(data.GetProperty("stage").GetString() == "cpu_task_event_wait", "stage");
            Require(data.GetProperty("completed_health_samples").GetInt32() == 2, "health progress lost");
            Require(data.GetProperty("submitted_cpu_tasks").GetInt32() == 1, "CPU progress lost");
            Require(data.GetProperty("first_task_id").GetString() == taskId && data.GetProperty("last_task_id").GetString() == taskId, "task identity lost");
            Require(data.GetProperty("stage_elapsed_ms").GetDouble() >= 0, "elapsed");
            var chain = data.GetProperty("exceptions").EnumerateArray().ToArray();
            Require(chain.Any(item => item.TryGetProperty("api_code", out var value) && value.GetString() == "NETWORK_ERROR"), "ApiException code lost");
            Require(chain.Any(item => item.TryGetProperty("http_request_error", out var value) && value.GetString() == "ConnectionError"), "HttpRequestError lost");
            Require(chain.Any(item => item.TryGetProperty("socket_error_code", out var value) && value.GetString() == "ConnectionRefused"), "real socket error lost");
            Require(chain.All(item => item.TryGetProperty("hresult", out _)), "HResult lost");
        }
        foreach (var stage in new[] { "credential_read", "rest_health", "websocket_connect", "cpu_task_submit", "cpu_task_event_wait", "websocket_ping", "report_write" }) {
            var value = new DiagnosticFailureContext(new Uri("http://127.0.0.1:1"));
            value.EnterStage(stage);
            await value.TryWriteAsync(Path.Combine(root, stage), new Win32Exception(5, secret));
            using var doc = JsonDocument.Parse(File.ReadAllText(Directory.GetFiles(root, stage + ".failure-context.*.json").Single()));
            Require(doc.RootElement.GetProperty("stage").GetString() == stage, "stage roundtrip");
        }
        Exception nested = new InvalidOperationException(secret);
        for (var i = 0; i < 20; i++) nested = new InvalidOperationException(secret, nested);
        await context.TryWriteAsync(Path.Combine(root, "bounded"), nested);
        var bounded = File.ReadAllText(Directory.GetFiles(root, "bounded.failure-context.*.json").Single());
        using (var doc = JsonDocument.Parse(bounded)) Require(doc.RootElement.GetProperty("exceptions").GetArrayLength() == 8, "unbounded chain");
        Require(bounded.Length < 16384 && !bounded.Contains(secret), "unbounded or unredacted evidence");
        // ── Sidecar I/O failure must not replace the legacy program's failure/exit path.
        await context.TryWriteAsync(Path.Combine(root, "absent", "report"), nested);
        Console.WriteLine("DIAGNOSTICS_FAILURE_CONTEXT_NATIVE_NEGATIVES=PASS; REAL_SOCKET=ConnectionRefused; GPU_POST=0");
    }
    private static void Require(bool passed, string message) { if (!passed) throw new Exception(message); }
}
'@
Add-Type -TypeDefinition ($usings + "`nnamespace PicotooPet.Desktop.Core.Networking {`n" + $apiSource + "`n}`nnamespace PicotooPet.Desktop.Diagnostics {`n" + $contextSource + "`n" + $fixture + "`n}")
[PicotooPet.Desktop.Diagnostics.FailureContextNegativeFixture]::Run().GetAwaiter().GetResult()
