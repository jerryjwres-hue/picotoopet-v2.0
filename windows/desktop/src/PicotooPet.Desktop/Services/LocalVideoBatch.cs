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
        // 与 GPU Bridge 共用安装包内的现有 Python Worker，不依赖 Windows py 启动器。
        // 缺失时严格报错；绝不从 PATH 搜索未知 Python 或自动联网下载。
        var worker = Path.Combine(
            AppContext.BaseDirectory, "tools", "worker",
            "PicotooPet.Worker", "PicotooPet.Worker.exe");
        if (!File.Exists(worker))
        {
            throw new InvalidOperationException(
                "安装包缺少受校验的视频 Worker，请重新验证或回滚安装。");
        }
        var start = new ProcessStartInfo(worker)
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
            RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        foreach (var arg in new[] { "--internal-import", "--project-root", project.FullName,
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
