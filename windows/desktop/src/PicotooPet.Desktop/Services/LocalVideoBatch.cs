using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Services;

public sealed record LocalBatchRequest(string Receipt, string EpisodeId, string Title, string Prefix,
    string EpisodeFile, string DecisionsFile, bool Thumbnails, bool Probe, string? PagePath,
    string RetakesFile = "", string CutPlanFile = "", string CutVideoFile = "");

/// <summary>在 Windows 本机解析已完成的批次，设备令牌由现有网络客户端管理。</summary>
public static class LocalVideoBatch
{
    public static async Task<JsonElement> PrepareAsync(LocalBatchRequest options, CancellationToken token)
    {
        ArgumentNullException.ThrowIfNull(options);
        var done = new FileInfo(options.Receipt).Directory;
        if (!string.Equals(done?.Name, "done", StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(done?.Parent?.Name, "_queue", StringComparison.OrdinalIgnoreCase) ||
            done?.Parent?.Parent is not { } project)
        {
            throw new InvalidOperationException("请选择项目 _queue\\done 下的 .result.json 完成回执。");
        }
        // 正式 Release 永远使用经安装清单 SHA 验证的内置 Worker；不依赖系统 py.exe。
        // 仅开发 DEBUG 构建允许测试脚本直跑，避免 WPF 冒烟测试伪造已打包成果。
        var worker = Path.Combine(
            AppContext.BaseDirectory, "tools", "worker",
            "PicotooPet.Worker", "PicotooPet.Worker.exe");
        ProcessStartInfo start;
        if (File.Exists(worker))
        {
            start = new ProcessStartInfo(worker);
            start.ArgumentList.Add("--internal-import");
        }
        else
        {
#if DEBUG
            // 开发测试：该分支不可能进入经签名/清单校验的 Release 安装包。
            var script = Path.Combine(
                AppContext.BaseDirectory, "ReviewTools", "import_video_candidates.py");
            if (!File.Exists(script))
            {
                throw new InvalidOperationException("测试工程缺少本地批次导入脚本。");
            }
            start = new ProcessStartInfo("py");
            foreach (var arg in new[] { "-3", "-X", "utf8", "-B", script })
            {
                start.ArgumentList.Add(arg);
            }
#else
            throw new InvalidOperationException(
                "正式安装包缺少经校验的 Worker；请运行安装验证或回滚。");
#endif
        }
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        start.StandardOutputEncoding = Encoding.UTF8;
        start.StandardErrorEncoding = Encoding.UTF8;
        foreach (var arg in new[] { "--project-root", project.FullName,
            "--receipt", options.Receipt }) start.ArgumentList.Add(arg);
        void Option(string name, string? value)
        {
            if (!string.IsNullOrWhiteSpace(value))
            {
                start.ArgumentList.Add(name);
                start.ArgumentList.Add(value);
            }
        }
        if (string.IsNullOrWhiteSpace(options.EpisodeFile)) Option("--episode-id", options.EpisodeId);
        else Option("--episode", options.EpisodeFile);
        Option("--title", options.Title);
        Option("--shot-prefix", options.Prefix);
        Option("--decisions", options.DecisionsFile);
        Option("--retakes", options.RetakesFile);
        if (options.Probe) start.ArgumentList.Add("--probe");
        if (options.PagePath is { } page)
        {
            Option("--review-page", page);
            Option("--cut-plan", options.CutPlanFile);
            Option("--cut-video", options.CutVideoFile);
        }
        else
        {
            start.ArgumentList.Add("--emit-manifest");
            if (options.Thumbnails) start.ArgumentList.Add("--thumbnails");
        }
        using var process = new Process { StartInfo = start };
        try { process.Start(); }
        catch (System.ComponentModel.Win32Exception ex)
        {
            throw new InvalidOperationException("无法启动安装包内的视频 Worker，请运行安装验证。", ex);
        }
        try
        {
            var output = process.StandardOutput.ReadToEndAsync(token);
            var error = process.StandardError.ReadToEndAsync(token);
            await Task.WhenAll(output, error, process.WaitForExitAsync(token)).ConfigureAwait(false);
            if (process.ExitCode != 0)
            {
                throw new InvalidOperationException((await error.ConfigureAwait(false)).Trim());
            }
            return JsonSerializer.Deserialize<JsonElement>(await output.ConfigureAwait(false));
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            throw;
        }
    }
}
