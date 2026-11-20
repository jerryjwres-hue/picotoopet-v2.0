using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Production.SmokeTests;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        var app = new Application();
        var result = 1;
        app.Dispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                VerifyBatchProfile();
                VerifyWorkerManagerSafety();
                if (args.FirstOrDefault() == "--live-core") await VerifyLiveAsync();
                else await VerifyAsync(args.FirstOrDefault());
                Console.WriteLine("PRODUCTION_DESKTOP_SMOKE=PASS");
                result = 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(exception);
            }
            finally
            {
                app.Shutdown();
            }
        }));
        app.Run();
        return result;
    }

    /// <summary>Windows 原生测试仅验证 Worker 启动前门禁，绝不启动 GPU。</summary>
    private static void VerifyWorkerManagerSafety()
    {
        // 默认配置只允许走 Windows 本机 OpenSSH 端口；不再默认把设备令牌发到局域网。
        Check(DesktopSettings.Default.MacBaseUrl == "http://127.0.0.1:18766",
            "Windows Studio 默认地址必须走本机加密隧道");
        Check(WorkerProcessManager.IsSecureCoreAddress(DesktopSettings.Default.MacBaseUrl),
            "默认本机安全地址被 Worker 错误拒绝");
        Check(WorkerProcessManager.IsSecureCoreAddress("https://mac.example.test:8766"),
            "HTTPS Mac 地址不应被拒绝");
        Check(WorkerProcessManager.IsSecureCoreAddress("http://127.0.0.1:8766"),
            "环回 HTTP 本地诊断不应被拒绝");
        Check(!WorkerProcessManager.IsSecureCoreAddress("http://192.168.1.161:8766"),
            "局域网 HTTP 不能承载 Worker 设备 Bearer");
        Check(!WorkerProcessManager.IsSecureCoreAddress("https://user:pass@mac.example.test"),
            "带明文 URI 凭据的 Mac 地址必须拒绝");
        Check(!WorkerProcessManager.IsSecureCoreAddress("https://mac.example.test/x"),
            "Worker Core 地址不接受额外 API 路径");
        Check(!WorkerProcessManager.IsValidWorkerId("../legacy"),
            "Worker ID 不能写入任意路径");
        Check(WorkerProcessManager.IsValidWorkerId("edit-workstation"),
            "合法 Worker ID 应通过");
        Check(WorkerProcessManager.IsValidSecret(new string('w', 48)),
            "合法 base64url HMAC 密钥应通过");
        Check(!WorkerProcessManager.IsValidSecret("short"),
            "不允许低强度配对密钥");

        var root = Directory.CreateTempSubdirectory("picotoo-worker-lock-");
        try
        {
            var queue = Path.Combine(root.FullName, "_queue");
            var lockDir = Path.Combine(queue, "executor_bridge");
            Directory.CreateDirectory(lockDir);
            using var manager = new WorkerProcessManager(
                Path.Combine(root.FullName, "missing-worker.exe"),
                Path.Combine(root.FullName, "worker.config.toml"));
            var refused = false;
            try
            {
                manager.Start(
                    "http://192.168.1.161:8766", root.FullName, "edit-workstation",
                    "synthetic-device-only", new string('w', 48));
            }
            catch (InvalidOperationException)
            {
                refused = true;
            }
            Check(refused, "不安全 Mac URL 意外启动 Worker");
            Check(!File.Exists(Path.Combine(root.FullName, "worker.config.toml")),
                "失败预检不应落盘配置或密钥");

            var lockPath = Path.Combine(lockDir, "edit-workstation.lock");
            using (var stream = new FileStream(
                lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite))
            {
                stream.Lock(0, 1);
                Check(WorkerProcessManager.ExistingWorkerOwnsLock(
                    root.FullName, "edit-workstation"), "没有识别已占用的 Bridge 独占锁");
                stream.Unlock(0, 1);
            }
            Check(!WorkerProcessManager.ExistingWorkerOwnsLock(
                root.FullName, "edit-workstation"), "未持锁时不应报告 Worker 正在运行");
        }
        finally
        {
            root.Delete(recursive: true);
        }
    }

    private static async Task VerifyAsync(string? screenshot)
    {
        using var transport = new FixtureTransport();
        using var http = new HttpClient(transport) { BaseAddress = new Uri("http://localhost") };
        await using var client = new MacCoreClient(http, Guid.NewGuid().ToString("N"));
        var model = new ProductionViewModel(() => client, () => CancellationToken.None);
        var view = new ProductionView { DataContext = model, Background = Brushes.White };
        await model.RefreshAsync();

        Check(model.Episode?.EpisodeId == "demo", "缺少剧集");
        Check(model.Shot?.ShotId == "S01", "没有默认选中分镜");
        Check(!model.AssembleCommand.CanExecute(null), "缺少选用时合成按钮应禁用");
        Check(model.PickLabel == "人工复核选用", "未明确标示末轮人工复核");
        Check(model.Candidates.Count == 3, "候选数量不匹配");
        Check(model.PlayCommand.CanExecute(null), "本机视频未提供播放入口");
        Check(model.QcText.Contains("通过", StringComparison.Ordinal), "没有显示中文质检字段");
        Check(model.QcText.Contains("92") && model.Candidates[0].Report is not null, "质检得分或报告图缺失");
        Check(model.Candidates.All(item => item.Preview is not null), "候选缩略图未显示");
        Check(model.Candidates[0].Origin.Contains("123", StringComparison.Ordinal), "缺少原始种子");
        Check(model.Candidates[0].Origin.Contains("fixture", StringComparison.Ordinal), "缺少原始批次");

        var artifactEvent = new EventEnvelope("2.2.0", 1, "a", "artifact.decided", null,
            DateTimeOffset.UtcNow, JsonSerializer.SerializeToElement(new { }));
        Check(artifactEvent.IsProductionChange(), "审片事件未触发生产页刷新");
        Check((artifactEvent with { Topic = "episode.imported" }).IsProductionChange(), "导入后没有刷新生产页");
        Check((artifactEvent with
        {
            Topic = "task.updated",
            Payload = JsonSerializer.SerializeToElement(new { task_type = "gen.foley" }),
        }).IsProductionChange(), "生产任务事件未触发刷新");
        Check(!(artifactEvent with
        {
            Topic = "task.updated",
            Payload = JsonSerializer.SerializeToElement(new { task_type = "analysis" }),
        }).IsProductionChange(), "无关任务触发了生产页刷新");

        transport.MacNote = "其他设备的备注";
        await model.RefreshAsync();
        Check(model.Note == transport.MacNote, "没有载入远端备注");
        model.Note = "本机编辑中";
        transport.MacNote = "另一位审片人刚刚更新";
        await model.RefreshAsync();
        Check(model.HasNoteConflict && !model.PickCommand.CanExecute(null), "备注冲突可被直接覆盖");
        model.UseMacNoteCommand.Execute(null);
        Check(!model.HasNoteConflict && model.Note == transport.MacNote, "未采用 Mac 的备注");
        model.Note = "示例备注。";
        model.PickCommand.Execute(null);
        await WaitForAsync(() => model.AssembleCommand.CanExecute(null));
        Check(transport.DecisionNote == "示例备注。", "审片备注未通过网络层提交");
        model.AssembleCommand.Execute(null);
        await WaitForAsync(() => model.Message.Contains("已入队", StringComparison.Ordinal));
        Check(transport.AssemblyCalls == 1, "没有创建合成任务");
        await VerifyLocalBatchAsync(model, transport);

        if (screenshot is not null)
        {
            RenderScreenshot(view, screenshot);
        }
    }

    // 实际网络自测只接受测试进程创建的环回服务和一次性令牌。
    private static async Task VerifyLiveAsync()
    {
        var uri = new Uri(Environment.GetEnvironmentVariable("PICOTOO_TEST_CORE_URL") ?? "");
        if (!uri.IsLoopback) throw new InvalidOperationException("集成测试需要环回服务。");
        var token = Environment.GetEnvironmentVariable("PICOTOO_TEST_CORE_TOKEN") ?? "";
        using var http = new HttpClient { BaseAddress = uri };
        await using var client = new MacCoreClient(http, token);
        var model = new ProductionViewModel(() => client, () => CancellationToken.None);
        var receipt = Environment.GetEnvironmentVariable("PICOTOO_TEST_RECEIPT") ?? "";
        await model.ProcessBatchAsync(new LocalBatchRequest(receipt, "demo", "", "fixture_", "", "", true, true, null));
        Check(model.Message.Contains("新增 1", StringComparison.Ordinal), model.Message);
        Check(model.Candidate?.Record.TaskType == "review.imported", "未读取 Core 登记的候选");
        Check(model.Candidate?.Record.Seed == 123, "真实服务的候选种子不同");
        model.Note = "已选用历史片，仍需独立 QC。";
        model.PickCommand.Execute(null);
        await WaitForAsync(() => model.Message.Contains("已记录选用", StringComparison.Ordinal));
        Check(!model.AssembleCommand.CanExecute(null), "历史素材没有当前 QC 认证，不应解锁合成。");
    }

    private static async Task VerifyLocalBatchAsync(ProductionViewModel model, FixtureTransport transport)
    {
        var root = Directory.CreateTempSubdirectory("picotoo-review-");
        try
        {
            var board = root.CreateSubdirectory("17_静态首帧板V2");
            var done = root.CreateSubdirectory("_queue/done");
            var output = root.CreateSubdirectory("output");
            var timestamp = DateTime.UtcNow.AddMinutes(-5);
            var frame = Path.Combine(board.FullName, "first.png");
            File.WriteAllBytes(frame, [1]);
            var jobs = Path.Combine(board.FullName, "jobs_demo.json");
            File.WriteAllText(jobs, JsonSerializer.Serialize(new
            {
                @out = "../output",
                jobs = new[] { new { id = "S01", first = "first.png", prompt = "A moving shape.",
                    seeds = (int[])[123], seconds = 3, w = 544, h = 960, fps = 24 } },
            }));
            File.SetLastWriteTimeUtc(jobs, timestamp);
            var queueFile = Path.Combine(done.FullName, "demo.json");
            File.WriteAllText(queueFile, """{"runner":"run_ltx_flf.py","jobs":"jobs_demo.json"}""");
            File.SetLastWriteTimeUtc(queueFile, timestamp.AddSeconds(10));
            var clip = Path.Combine(output.FullName, "S01_v1.mp4");
            File.WriteAllBytes(clip, [1, 2, 3]);
            File.SetLastWriteTimeUtc(clip, timestamp.AddSeconds(20));
            var receipt = Path.Combine(done.FullName, "demo.result.json");
            File.WriteAllText(receipt, """{"task":"demo","runner":"run_ltx_flf.py","ok":true,"returncode":0,"fails":[],"outputs":["output/S01_v1.mp4"]}""");
            var options = new LocalBatchRequest(receipt, "demo", "", "", "", "", false, false, null);
            await model.ProcessBatchAsync(options);
            Check(transport.ImportCalls == 1, "按钮未通过已连接的 Mac 客户端导入");
            Check(model.Message.Contains("新增 1", StringComparison.Ordinal), "没有显示服务端导入计数");
            var offline = Path.Combine(root.FullName, "review.html");
            await LocalVideoBatch.PrepareAsync(options with { PagePath = offline }, CancellationToken.None);
            Check(File.ReadAllText(offline).Contains("S01_v1.mp4", StringComparison.Ordinal), "未能离线创建审片页");
        }
        finally
        {
            root.Delete(true);
        }
    }

    private static async Task WaitForAsync(Func<bool> predicate)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (!predicate())
        {
            await Task.Delay(15, timeout.Token);
        }
    }

    private static void VerifyBatchProfile()
    {
        var directory = Directory.CreateTempSubdirectory("picotoo-profile-");
        var file = Path.Combine(directory.FullName, "settings.json");
        try
        {
            var receipt = Path.Combine(directory.FullName, "queue", "fixture.result.json");
            var cutPlan = Path.Combine(directory.FullName, "plan.json");
            var profile = new LocalBatchProfile(receipt, "demo", "Fixture", "T_",
                RetakesFile: receipt, CutPlanFile: cutPlan, CutVideoFile: receipt,
                Thumbnails: false, Probe: true);
            LocalBatchProfile.Save(file, profile);
            using (var document = JsonDocument.Parse(File.ReadAllText(file)))
            {
                var data = document.RootElement;
                Check(!Path.IsPathRooted(data.GetProperty("receipt").GetString()), "配置应保存相对路径");
                Check(data.GetProperty("version").GetInt32() == 1, "配置缺少版本");
                Check(!data.TryGetProperty("decisions_file", out _), "配置带了离线决定");
            }
            Check(LocalBatchProfile.Load(file) == profile, "审片配置读写往返时丢失字段");
            File.WriteAllText(file, """{"version":1,"receipt":"x.result.json","command":"run"}""");
            try
            {
                LocalBatchProfile.Load(file);
                throw new InvalidOperationException("配置含未定义字段时仍通过");
            }
            catch (JsonException) { }
        }
        finally
        {
            File.Delete(file);
            directory.Delete();
        }
    }

    private static void RenderScreenshot(ProductionView view, string destination)
    {
        var root = new DockPanel { Background = Brushes.White };
        var tabs = new TabControl { Margin = new Thickness(12), SelectedIndex = 1 };
        tabs.Items.Add(new TabItem { Header = "总览" });
        tabs.Items.Add(new TabItem { Header = "生产", Content = view });
        tabs.Items.Add(new TabItem { Header = "连接设置" });
        root.Children.Add(tabs);
        var dimensions = new Size(1080, 620);
        root.Measure(dimensions);
        root.Arrange(new Rect(dimensions));
        root.UpdateLayout();
        var pixels = new RenderTargetBitmap(1080, 620, 96, 96, PixelFormats.Pbgra32);
        pixels.Render(root);
        var png = new PngBitmapEncoder();
        png.Frames.Add(BitmapFrame.Create(pixels));
        using var file = File.Create(destination);
        png.Save(file);
    }

    private static void Check(bool condition, string failure)
    {
        if (!condition)
        {
            throw new InvalidOperationException(failure);
        }
    }

    private sealed class FixtureTransport : HttpMessageHandler
    {
        private bool _picked;
        public string? DecisionNote { get; private set; }
        public string MacNote { get; set; } = "";
        public int AssemblyCalls { get; private set; }
        public int ImportCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var route = request.RequestUri!.AbsolutePath;
            switch (route)
            {
                case "/api/v1/episodes/import":
                    using (var data = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(cancellationToken)))
                    {
                        var clip = data.RootElement.GetProperty("candidates")[0];
                        Check(clip.GetProperty("seed").GetInt32() == 123, "导入的种子错误");
                        Check(clip.GetProperty("bytes").GetInt64() == 3, "导入的字节数错误");
                        Check(!clip.TryGetProperty("jpeg_base64", out _), "关闭预览后仍附有媒体");
                        Check(request.Headers.Authorization?.Scheme == "Bearer", "导入未复用设备鉴权");
                    }
                    ImportCalls++;
                    return Json(new { episode_id = "demo", inserted_count = 1, existing_count = 0 });
                case "/api/v1/episodes":
                    return Json(new[] { new { episode_id = "demo", title = "示例剧集 · 纯色测试" } });
                case "/api/v1/episodes/demo/review":
                    return Json(new
                    {
                        can_assemble = _picked,
                        shots = new[] {
                            new { shot_id = "S01", status = _picked ? "已选用" : "待审片", redo_count = 1,
                                candidates = new[] {
                                    Candidate("a", "video", "take_01.mp4", 1, _picked ? "pick" : null),
                                    Candidate("b", "video", "take_02.mp4", 2, null),
                                    Candidate("c", "image", "keyframe.jpg", 1, "pick"),
                                },
                            },
                            new { shot_id = "S02", status = "已选用", redo_count = 0,
                                candidates = new[] { Candidate("d", "video", "take_01.mp4", 1, "pick") },
                            },
                        },
                    });
                case "/api/v1/artifacts/a/decision":
                    using (var decision = JsonDocument.Parse(
                        await request.Content!.ReadAsStringAsync(cancellationToken)))
                    {
                        Check(decision.RootElement.GetProperty("accept_qc_failure").GetBoolean(), "未提交明确的人工放行标记");
                        _picked = decision.RootElement.GetProperty("decision").GetString() == "pick";
                        DecisionNote = decision.RootElement.GetProperty("note").GetString();
                        MacNote = DecisionNote ?? "";
                    }
                    return Json(new { decision = "pick" });
                case "/api/v1/episodes/demo/assemble":
                    AssemblyCalls++;
                    return Json(new { task_id = "fake-task", task_type = "edit.assemble", status = "Queued" });
                default:
                    if (route.StartsWith("/api/v1/tasks/fixture/thumbnails/", StringComparison.Ordinal))
                    {
                        return Json(new { jpeg_base64 = SolidColor(route[^1]) });
                    }
                    throw new InvalidOperationException($"测试收到意外请求 {route}");
            }
        }

        private object Candidate(string id, string kind, string file, int take, string? decision) =>
            new { artifact_id = id, task_id = "fixture", kind, path = $@"C:\Demo\{file}", take,
                decision, note = id == "a" ? MacNote : "", thumbnail_id = id, seed = 123, source_id = "fixture", task_type = "review.imported",
                qc = new { passed = false, gate_status = "QC_MANUAL_REVIEW", can_confirm = true, score = 92, fails = Array.Empty<string>(), report_task_id = "fixture", report_thumbnail_id = "report" },
            };

        private static HttpResponseMessage Json<T>(T value) => new(HttpStatusCode.OK)
        {
            Content = new StringContent(JsonSerializer.Serialize(value), Encoding.UTF8, "application/json"),
        };

        private static string SolidColor(char take)
        {
            var color = take switch
            {
                'a' => Color.FromRgb(57, 109, 124),
                'b' => Color.FromRgb(117, 110, 164),
                _ => Color.FromRgb(194, 148, 91),
            };
            var visual = new DrawingVisual();
            using (var drawing = visual.RenderOpen())
            {
                drawing.DrawRectangle(new SolidColorBrush(color), null, new Rect(0, 0, 160, 90));
            }
            var bitmap = new RenderTargetBitmap(160, 90, 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(visual);
            var jpeg = new JpegBitmapEncoder();
            jpeg.Frames.Add(BitmapFrame.Create(bitmap));
            using var bytes = new MemoryStream();
            jpeg.Save(bytes);
            return Convert.ToBase64String(bytes.ToArray());
        }
    }
}
