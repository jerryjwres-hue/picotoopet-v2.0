using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Services;

/// <summary>管理安装包内的同一个 GPU Bridge；不持有 Core 审批权或第二套任务队列。</summary>
public sealed class WorkerProcessManager : IDisposable
{
    private static readonly Regex WorkerIdPattern =
        new("^[A-Za-z0-9_-]{1,100}$", RegexOptions.CultureInvariant);
    private static readonly Regex SecretPattern =
        new("^[A-Za-z0-9_-]{43,256}$", RegexOptions.CultureInvariant);

    private readonly string _executable;
    private readonly string _configFile;
    private Process? _ownedProcess;

    public WorkerProcessManager(string executable, string configFile)
    {
        _executable = Path.GetFullPath(executable);
        _configFile = Path.GetFullPath(configFile);
    }

    /// <summary>只能是 HTTPS Mac 或本机 loopback；防止设备令牌经 LAN 明文发送。</summary>
    public static bool IsSecureCoreAddress(string address)
    {
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri)
            || !string.IsNullOrEmpty(uri.UserInfo)
            || !string.IsNullOrEmpty(uri.Query)
            || !string.IsNullOrEmpty(uri.Fragment)
            || uri.AbsolutePath != "/")
        {
            return false;
        }
        return uri.Scheme == Uri.UriSchemeHttps
            || (uri.Scheme == Uri.UriSchemeHttp
                && (uri.IsLoopback || string.Equals(uri.Host, "127.0.0.1", StringComparison.Ordinal)));
    }

    public static bool IsValidWorkerId(string workerId) =>
        WorkerIdPattern.IsMatch(workerId);

    public static bool IsValidSecret(string secret) =>
        SecretPattern.IsMatch(secret);

    /// <summary>现有 Python Bridge 以一字节锁防双实例；不依赖可能失效的 PID 缓存。</summary>
    public static bool ExistingWorkerOwnsLock(string projectRoot, string workerId)
    {
        if (!IsValidWorkerId(workerId) || !Directory.Exists(projectRoot))
            return false;

        var lockPath = Path.Combine(
            projectRoot, "_queue", "executor_bridge", $"{workerId}.lock");
        if (!File.Exists(lockPath))
            return false;

        try
        {
            using var stream = new FileStream(
                lockPath, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite);
            stream.Lock(0, 1);
            stream.Unlock(0, 1);
            return false;
        }
        catch (IOException)
        {
            // Windows 对锁定字节的拒绝证明进程仍持有现有 Bridge 互斥锁。
            return true;
        }
        catch (UnauthorizedAccessException)
        {
            // 权限不明不代表合法运行；由 Start 阶段继续按失败处理。
            return false;
        }
    }

    /// <summary>仅启动已安装的原有 Worker EXE；不生成 GPU inbox 或 Mac 生产许可。</summary>
    public string Start(
        string coreAddress,
        string projectRoot,
        string workerId,
        string deviceToken,
        string attestationSecret)
    {
        if (!IsSecureCoreAddress(coreAddress))
            throw new InvalidOperationException("Mac Core 必须使用 HTTPS；只有本机 loopback 可用 HTTP。");
        if (!IsValidWorkerId(workerId) || !IsValidSecret(attestationSecret))
            throw new InvalidOperationException("Worker ID 或独立配对密钥格式无效。");
        if (string.IsNullOrWhiteSpace(deviceToken))
            throw new InvalidOperationException("请先与 Mac Core 完成设备配对。");
        if (!Path.IsPathFullyQualified(projectRoot)
            || projectRoot.StartsWith(@"\\", StringComparison.Ordinal)
            || !Directory.Exists(Path.Combine(projectRoot, "_queue")))
        {
            throw new InvalidOperationException("先选择含 _queue 的 Windows 本地视频项目目录。");
        }
        if (!File.Exists(_executable))
            throw new InvalidOperationException("安装包缺少经发布清单验证的 Worker EXE。");

        if (ExistingWorkerOwnsLock(projectRoot, workerId))
            return "Worker 已在运行；保留原有 Journal，未启动第二进程。";

        // TOML 接受 JSON 的转义字符串；配置仅含 URL、Worker ID 与项目路径。
        // 设备 Bearer 与 HMAC 密钥只经进程环境和 Windows Credential Manager 传递。
        var config = new StringBuilder()
            .Append("mac_core_url = ").AppendLine(JsonSerializer.Serialize(coreAddress))
            .Append("worker_id = ").AppendLine(JsonSerializer.Serialize(workerId))
            .Append("project_root = ").AppendLine(JsonSerializer.Serialize(Path.GetFullPath(projectRoot)))
            .AppendLine("resource_tags = [\"gpu-5070ti\"]")
            .AppendLine("lease_seconds = 90")
            .ToString();

        var folder = Path.GetDirectoryName(_configFile)!;
        Directory.CreateDirectory(folder);
        if (File.Exists(_configFile)
            && (File.GetAttributes(_configFile) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("Worker 配置不能写入符号链接。");

        var temp = _configFile + ".tmp";
        if (File.Exists(temp) && (File.GetAttributes(temp) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("Worker 临时配置不能写入符号链接。");
        try
        {
            File.WriteAllText(temp, config, new UTF8Encoding(false));
            File.Move(temp, _configFile, overwrite: true);
        }
        finally
        {
            if (File.Exists(temp))
                File.Delete(temp);
        }

        var start = new ProcessStartInfo(_executable)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(_executable)!,
        };
        start.ArgumentList.Add(_configFile);
        start.Environment["PICOTOO_EXECUTOR_TOKEN"] = deviceToken;
        start.Environment["PICOTOO_WORKER_ATTEST_KEY"] = attestationSecret;

        var process = Process.Start(start)
            ?? throw new InvalidOperationException("安装包内的 Worker 无法启动。");
        // 只识别启动立即失败，绝不等待模型或 Comfy；不会向 Mac 下发任务。
        if (process.WaitForExit(250))
        {
            var exitCode = process.ExitCode;
            process.Dispose();
            throw new InvalidOperationException($"Worker 启动后立即退出（{exitCode}），请核查视频项目和配对配置。");
        }
        _ownedProcess?.Dispose();
        _ownedProcess = process;
        return "原有 Windows Worker 已启动；仍需有效 Owner/MASTER/冻结 Plan 才能取得 GPU 租约。";
    }

    /// <summary>调用现有 --pause-new / --resume-new；不终止已有 GPU 任务或 Journal。</summary>
    public void SetNewLeasesPaused(bool paused)
    {
        if (!File.Exists(_executable) || !File.Exists(_configFile))
            throw new InvalidOperationException("请先完成 Worker 一次性配置。");
        var start = new ProcessStartInfo(_executable)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(_executable)!,
        };
        start.ArgumentList.Add(_configFile);
        start.ArgumentList.Add(paused ? "--pause-new" : "--resume-new");
        using var process = Process.Start(start)
            ?? throw new InvalidOperationException("无法启动本地 Worker 暂停操作。");
        if (!process.WaitForExit(8000))
        {
            process.Kill(entireProcessTree: true);
            throw new TimeoutException("Worker 暂停操作超时，未声明状态修改成功。");
        }
        if (process.ExitCode != 0)
            throw new InvalidOperationException("Worker 暂停状态操作失败，请核查项目配置。");
    }

    /// <summary>关闭 Studio 不杀死可能仍在处理旧 Journal 的 Worker，避免损坏正在运行的 GPU 作业。</summary>
    public void Dispose()
    {
        _ownedProcess?.Dispose();
        _ownedProcess = null;
    }
}
