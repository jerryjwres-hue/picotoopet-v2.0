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
                await VerifyAsync(args.FirstOrDefault());
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
        Check(model.Candidates.Count == 3, "候选数量不匹配");
        Check(model.PlayCommand.CanExecute(null), "本机视频未提供播放入口");
        Check(model.QcText.Contains("通过", StringComparison.Ordinal), "没有显示中文质检字段");
        Check(model.Candidates.All(item => item.Preview is not null), "候选缩略图未显示");

        var artifactEvent = new EventEnvelope("2.2.0", 1, "a", "artifact.decided", null,
            DateTimeOffset.UtcNow, JsonSerializer.SerializeToElement(new { }));
        Check(artifactEvent.IsProductionChange(), "审片事件未触发生产页刷新");
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

        model.Note = "示例备注。";
        model.PickCommand.Execute(null);
        await WaitForAsync(() => model.AssembleCommand.CanExecute(null));
        Check(transport.DecisionNote == "示例备注。", "审片备注未通过网络层提交");
        model.AssembleCommand.Execute(null);
        await WaitForAsync(() => model.Message.Contains("已入队", StringComparison.Ordinal));
        Check(transport.AssemblyCalls == 1, "没有创建合成任务");

        if (screenshot is not null)
        {
            RenderScreenshot(view, screenshot);
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
        public int AssemblyCalls { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var route = request.RequestUri!.AbsolutePath;
            switch (route)
            {
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
                        _picked = decision.RootElement.GetProperty("decision").GetString() == "pick";
                        DecisionNote = decision.RootElement.GetProperty("note").GetString();
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

        private static object Candidate(string id, string kind, string file, int take, string? decision) =>
            new { artifact_id = id, task_id = "fixture", kind, path = $@"C:\Demo\{file}", take,
                decision, note = "", thumbnail_id = id,
                qc = new { 通过 = true, 秒数 = 3.0, 宽 = 576, 高 = 768, 有音轨 = true },
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
