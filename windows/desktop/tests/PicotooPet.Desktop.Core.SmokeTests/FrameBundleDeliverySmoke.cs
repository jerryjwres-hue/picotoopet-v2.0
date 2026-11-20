using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>无 Python、无用户素材、无 GPU 的原生 .NET 双机素材交接回归。</summary>
internal static class FrameBundleDeliverySmoke
{
    private static readonly byte[] SyntheticPng = Convert.FromBase64String(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC" +
        "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZcAAAAASUVORK5CYII=");

    public static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"picotoo-frame-native-{Guid.NewGuid():N}");
        var project = Path.Combine(root, "windows-worker");
        var board = Path.Combine(project, "17_静态首帧板V2");
        Directory.CreateDirectory(board);
        try
        {
            var objectSha = Sha(SyntheticPng);
            var manifest = JsonSerializer.SerializeToUtf8Bytes(new
            {
                bindings = new[] {
                    new {
                        asset_ref = "maotai_master_v1", managed_sha256 = objectSha,
                        role = "first", shot_id = "S01",
                    },
                },
                contract = "picotoo.frame-source-manifest.v1",
                owner_subject_sha256 = new string('b', 64),
                storypack_sha256 = new string('a', 64),
            });
            var manifestSha = Sha(manifest);
            var archive = Path.Combine(root, "synthetic-frames.zip");
            using (var writer = ZipFile.Open(archive, ZipArchiveMode.Create))
            {
                // 与 Mac 的内容寻址清单完全一致；所有内容是合成的 1×1 图片。
                Add(writer, "manifest.json", manifest);
                Add(writer, $"objects/{objectSha}", SyntheticPng);
            }

            var bundleBytes = await File.ReadAllBytesAsync(archive);
            var bundleSha = Sha(bundleBytes);
            var first = await FrameBundleStager.StageAsync(archive, manifestSha, project);
            Assert(first.WorkerLocalBytesVerified, "Windows 未验证目标内容");
            Assert(!first.CanQueue && !first.GpuAuthorized, "数据暂存越权");
            Assert(first.Bindings.Count == 1, "多出未声明素材");
            var workerPath = Path.GetFullPath(Path.Combine(board, first.Bindings[0].WorkerRef));
            Assert(Sha(await File.ReadAllBytesAsync(workerPath)) == objectSha, "本地哈希错误");

            var second = await FrameBundleStager.StageAsync(archive, manifestSha, project);
            Assert(second.Bindings[0].WorkerRef == first.Bindings[0].WorkerRef,
                "重复导入没有复用正确 SHA 路径");
            await AssertThrowsAsync(
                () => FrameBundleStager.StageAsync(archive, new string('c', 64), project),
                "错误 Plan 摘要未被拒绝");

            // 已落地但被修改的素材不得继续复用，也不能静默替换。
            await File.WriteAllBytesAsync(workerPath, new byte[] { 1, 2, 3, 4 });
            await AssertThrowsAsync(
                () => FrameBundleStager.StageAsync(archive, manifestSha, project),
                "旧素材被篡改仍未阻止");

            File.Delete(workerPath);
            var handler = new SyntheticCoreHandler(bundleBytes, manifestSha, bundleSha);
            using var client = new HttpClient(handler)
            {
                BaseAddress = new Uri("https://mac.example/"),
                Timeout = TimeSpan.FromSeconds(60),
            };
            await using var mac = new MacCoreClient(client, "device-test-token");
            var native = await mac.DownloadAndStageFramesAsync(
                "one-use-transfer-ticket-0123456789", manifestSha, bundleSha, project);
            Assert(native.WorkerLocalBytesVerified && !native.CanQueue && !native.GpuAuthorized,
                "已验证传输意外获得 GPU 权限");
            Assert(handler.Calls == 1, "原生客户端请求数量不匹配");

            // Windows 普通 LAN 明文 HTTP 必须在发送任何请求前直接拒绝。
            using var insecure = new HttpClient(new SyntheticCoreHandler(bundleBytes, manifestSha, bundleSha))
            {
                BaseAddress = new Uri("http://192.0.2.30:8766/"),
            };
            await using var insecureMac = new MacCoreClient(insecure, "device-test-token");
            await AssertThrowsAsync(
                () => insecureMac.DownloadAndStageFramesAsync(
                    "one-use-transfer-ticket-0123456789", manifestSha, bundleSha, project),
                "远程未加密 HTTP 不应允许私有素材下载");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static void Add(ZipArchive archive, string name, byte[] bytes)
    {
        var entry = archive.CreateEntry(name, CompressionLevel.NoCompression);
        using var output = entry.Open();
        output.Write(bytes);
    }

    private static string Sha(byte[] data) =>
        Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    private static void Assert(bool value, string message)
    {
        if (!value)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static async Task AssertThrowsAsync(Func<Task> operation, string message)
    {
        try
        {
            await operation();
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }

    /// <summary>只有客户端 HTTP 层采用合成响应；ZIP 落盘依然走真实 NTFS 文件系统。</summary>
    private sealed class SyntheticCoreHandler : HttpMessageHandler
    {
        private readonly byte[] _body;
        private readonly string _manifestSha;
        private readonly string _bundleSha;

        public int Calls { get; private set; }

        public SyntheticCoreHandler(byte[] body, string manifestSha, string bundleSha)
        {
            _body = body;
            _manifestSha = manifestSha;
            _bundleSha = bundleSha;
        }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            Assert(request.Method == HttpMethod.Get, "应使用 GET 下载素材");
            Assert(request.RequestUri?.AbsolutePath == "/api/v1/studio/frame-transfer/download",
                "下载路径错误");
            Assert(request.Headers.Authorization?.Scheme == "Bearer" &&
                request.Headers.Authorization.Parameter == "device-test-token",
                "未复用设备 Bearer");
            Assert(request.Headers.TryGetValues("X-Picotoo-Transfer-Ticket", out var values) &&
                values.Single() == "one-use-transfer-ticket-0123456789",
                "缺少 Owner 一次性 Ticket");

            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(_body),
            };
            response.Content.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
            response.Headers.Add("X-Picotoo-Source-Bindings-Sha256", _manifestSha);
            response.Headers.Add("X-Picotoo-Bundle-Sha256", _bundleSha);
            return Task.FromResult(response);
        }
    }
}
