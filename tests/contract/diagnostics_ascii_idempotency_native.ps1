param([Parameter(Mandatory)][string]$RepoRoot)
$ErrorActionPreference = 'Stop'
$source = Get-Content (Join-Path $RepoRoot 'windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs') -Raw
$keys = [regex]::Matches($source, '\$"phase2-diagnostic-[^"\r\n]+"')
if ($keys.Count -ne 1) { throw 'DIAGNOSTIC_KEY_EXPRESSION_NOT_UNIQUE' }
$expression = $keys[0].Value.Replace('Environment.MachineName', 'machineName')
$fixture = @'
#nullable enable
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
public static class DiagnosticAsciiTransportFixture {
    private static string CurrentKey(string machineName) => KEY_EXPRESSION;
    public static async Task Run() {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        var token = deadline.Token;
        // ── Confirm the exact old failure through the real handler, not a regex check.
        using (var listener = new TcpListener(IPAddress.Loopback, 0)) {
            listener.Start();
            var port = ((IPEndPoint)listener.LocalEndpoint).Port;
            var receive = Receive(listener, token);
            using var handler = new SocketsHttpHandler { UseProxy = false };
            using var client = new HttpClient(handler);
            using var request = MakeRequest(port, "phase2-diagnostic-中文机器-" + Guid.NewGuid().ToString("N"), "中文机器");
            try { using var response = await client.SendAsync(request, token); throw new Exception("Old non-ASCII header unexpectedly sent"); }
            catch (HttpRequestException error) {
                Require(error.HttpRequestError == HttpRequestError.Unknown && error.StatusCode is null && error.InnerException is null && error.HResult == unchecked((int)0x80131500), "Old error signature differs from live evidence");
            }
            Require(await receive is null, "Old invalid header reached HTTP task receiver");
            Console.WriteLine("OLD_HEADER_CAUSE_REPRODUCED=PASS; HttpRequestError=Unknown; HResult=0x80131500; HTTP_REQUESTS=0");
        }
        var names = new[] { "ASCII-HOST", "中文机器", "Ω-é-机器", "🐾🚀-pet", new string('界', 240), new string('A', 2048) };
        var generated = new HashSet<string>(StringComparer.Ordinal);
        foreach (var name in names) {
            // ── The tested expression is extracted from the actual production-tool source.
            var key = CurrentKey(name);
            Require(generated.Add(key), "Generated key is not unique");
            Require(key.Length <= 200 && key.All(character => character <= 127), "Diagnostic header is not bounded ASCII");
            Require(!key.Contains(name, StringComparison.Ordinal), "Machine audit identity leaked into header");
            using var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var port = ((IPEndPoint)listener.LocalEndpoint).Port;
            using var client = new HttpClient(new SocketsHttpHandler { UseProxy = false });
            // ── Reusing a caller-held key transmits it unchanged; JSON keeps the full audit name.
            for (var replay = 0; replay < 2; replay++) {
                var receive = Receive(listener, token);
                using var request = MakeRequest(port, key, name);
                using var response = await client.SendAsync(request, token);
                Require(response.StatusCode == HttpStatusCode.OK, "Actual current header transport failed");
                var observed = await receive;
                Require(observed is not null && observed.Value.Key == key && observed.Value.Machine == name, "Wire header or JSON audit name changed");
            }
        }
        Console.WriteLine("DIAGNOSTIC_ASCII_HTTP_TRANSPORT=PASS; HOST_CASES=6; POSTS=12; AUDIT_JSON_PRESERVED=PASS; STABLE_KEY=PASS; REAL_CORE_POST=0; GPU_POST=0");
    }
    private static HttpRequestMessage MakeRequest(int port, string key, string machine) {
        var request = new HttpRequestMessage(HttpMethod.Post, $"http://127.0.0.1:{port}/api/v1/tasks");
        request.Headers.TryAddWithoutValidation("Idempotency-Key", key);
        request.Content = new StringContent(JsonSerializer.Serialize(new { machine }), Encoding.UTF8, "application/json");
        return request;
    }
    private static async Task<(string Key, string Machine)?> Receive(TcpListener listener, CancellationToken token) {
        using var socket = await listener.AcceptTcpClientAsync(token);
        await using var stream = socket.GetStream();
        var data = new List<byte>();
        var buffer = new byte[1];
        while (true) {
            var read = await stream.ReadAsync(buffer, token);
            if (read == 0) return null;
            data.Add(buffer[0]);
            Require(data.Count < 64 * 1024, "Unbounded fixture HTTP headers");
            if (data.Count >= 4 && data.TakeLast(4).SequenceEqual(new byte[] {13, 10, 13, 10})) break;
        }
        var headers = Encoding.ASCII.GetString(data.ToArray()).Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        var key = headers.Single(line => line.StartsWith("Idempotency-Key:", StringComparison.OrdinalIgnoreCase)).Split(':', 2)[1].Trim();
        var length = int.Parse(headers.Single(line => line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)).Split(':', 2)[1], System.Globalization.CultureInfo.InvariantCulture);
        Require(length <= 64 * 1024, "Unbounded fixture JSON");
        var body = new byte[length];
        await stream.ReadExactlyAsync(body, token);
        using var document = JsonDocument.Parse(body);
        var machine = document.RootElement.GetProperty("machine").GetString()!;
        var response = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}");
        await stream.WriteAsync(response, token);
        return (key, machine);
    }
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
}
'@
Add-Type -TypeDefinition $fixture.Replace('KEY_EXPRESSION', $expression)
[DiagnosticAsciiTransportFixture]::Run().GetAwaiter().GetResult()
