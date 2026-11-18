using System.ComponentModel;
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
        var script = Path.Combine(AppContext.BaseDirectory, "ReviewTools", "import_video_candidates.py");
        var start = new ProcessStartInfo("py")
        {
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true,
            RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        foreach (var arg in new[] { "-3", "-X", "utf8", "-B", script, "--project-root", project.FullName,
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
        catch (Win32Exception ex)
        {
            throw new InvalidOperationException("无法启动 Python。请安装 Python 3.11 或更高版本及 Windows py 启动器。", ex);
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
