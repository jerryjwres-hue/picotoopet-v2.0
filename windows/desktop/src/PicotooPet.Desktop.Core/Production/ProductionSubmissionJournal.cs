using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>只记录提交不确定性，不保存 lease/token/原文，不替代 Core 成功/失败事实。</summary>
public sealed record ProductionSubmission(string JobId, string TaskId, string PlanDigest,
    string GraphDigest, string Phase, string? PromptId, string? FailureCode = null,
    string? PreviousPromptId = null, DateTimeOffset? PreviousTaskUpdatedAtUtc = null);

public sealed class ProductionWorkerException(string code) : Exception(code)
{
    public string Code { get; } = code;
}

/// <summary>每用户跨进程排他文件；崩溃自动释放句柄，未对账提交仍由 journal 阻止重复。</summary>
public sealed class ProductionSubmissionJournal
{
    private static readonly JsonSerializerOptions Strict = new()
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        RespectRequiredConstructorParameters = true,
        RespectNullableAnnotations = true,
    };
    public static string DefaultRoot => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PicotooPetV2", "MediaWorker", "v1");
    private readonly string _root;
    public ProductionSubmissionJournal(string root)
    {
        if (!Path.IsPathFullyQualified(root)) throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
        _root = Path.GetFullPath(root);
    }
    public IDisposable AcquireGpu() => Acquire("gpu.lock");
    public IDisposable AcquireRuntime() => Acquire("runtime.lock");
    private FileStream Acquire(string name)
    {
        EnsureRoot();
        if (File.Exists(Path.Combine(_root, name)) && (File.GetAttributes(Path.Combine(_root, name)) & FileAttributes.ReparsePoint) != 0)
            throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
        try { return new FileStream(Path.Combine(_root, name), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { throw new ProductionWorkerException("MEDIA_WORKER_BUSY"); }
    }
    private void EnsureRoot()
    {
        // 包括所有现有祖先，不跟随 junction / symlink 创建用户状态。
        for (DirectoryInfo? current = new(_root); current is not null; current = current.Parent)
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0) throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
        Directory.CreateDirectory(_root);
    }
    private string FileFor(string job, string task) => Path.Combine(_root, Hash(job + "\n" + task) + ".submission.json");
    public static string Hash(string text) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();
    public static string GraphDigest(System.Text.Json.Nodes.JsonObject graph) => Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(graph))).ToLowerInvariant();
    public ProductionSubmission? Read(string job, string task)
    {
        EnsureRoot();
        var file = FileFor(job, task);
        return File.Exists(file) ? ReadFile(file) : null;
    }
    public DateTimeOffset LastWriteUtc(string job, string task)
    {
        EnsureRoot();
        var file = FileFor(job, task);
        _ = Read(job, task) ?? throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
        return new DateTimeOffset(File.GetLastWriteTimeUtc(file), TimeSpan.Zero);
    }
    public IReadOnlyList<ProductionSubmission> Pending()
    {
        EnsureRoot();
        using var gate = Acquire("journal.lock");
        // Validate before pruning. Never remove uncertainty, malformed files, or links.
        var records = Directory.EnumerateFiles(_root, "*.submission.json")
            .Select(file => (File: file, Value: ReadFile(file))).ToArray();
        var pending = records.Where(r => r.Value.Phase != "Settled").Select(r => r.Value).ToArray();
        if (pending.Length > 1000) throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
        foreach (var old in records.Where(r => r.Value.Phase == "Settled")
            .OrderByDescending(r => File.GetLastWriteTimeUtc(r.File)).ThenBy(r => r.File, StringComparer.Ordinal).Skip(128))
            File.Delete(old.File);
        return pending;
    }
    private ProductionSubmission ReadFile(string file)
    {
        try
        {
            if ((File.GetAttributes(file) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0
                || new FileInfo(file).Length is <= 0 or > 16384) throw new JsonException();
            var value = JsonSerializer.Deserialize<ProductionSubmission>(File.ReadAllBytes(file), Strict) ?? throw new JsonException();
            Validate(value);
            if (Path.GetFullPath(file) != FileFor(value.JobId, value.TaskId)) throw new JsonException();
            return value;
        }
        catch (Exception e) when (e is JsonException or IOException or UnauthorizedAccessException)
        { throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID"); }
    }
    public void Save(ProductionSubmission value)
    {
        Validate(value); EnsureRoot();
        using var gate = Acquire("journal.lock");
        var target = FileFor(value.JobId, value.TaskId);
        var temporary = Path.Combine(_root, Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                stream.Write(JsonSerializer.SerializeToUtf8Bytes(value));
                stream.Flush(flushToDisk: true);
            }
            if (File.Exists(target)) _ = ReadFile(target);
            File.Move(temporary, target, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
    private static void Validate(ProductionSubmission s)
    {
        if (string.IsNullOrWhiteSpace(s.JobId) || s.JobId.Length > 160 || string.IsNullOrWhiteSpace(s.TaskId) || s.TaskId.Length > 160
            || !Sha(s.PlanDigest) || !Sha(s.GraphDigest) || s.Phase is not ("Prepared" or "RetryPrepared" or "Submitting" or "Submitted" or "FailurePending" or "Settled")
            || s.PromptId is { Length: > 200 } || s.PreviousPromptId is { Length: > 200 } 
            || (s.Phase == "RetryPrepared" && (s.PromptId is not null || string.IsNullOrWhiteSpace(s.PreviousPromptId)
                || s.PreviousTaskUpdatedAtUtc is null))
            || s.Phase is "Submitted" or "FailurePending" && string.IsNullOrWhiteSpace(s.PromptId)
            || s.Phase == "FailurePending" && s.FailureCode != "COMFY_RETRY_BUDGET_EXHAUSTED"
            || s.FailureCode is not (null or "COMFY_RETRY_BUDGET_EXHAUSTED"))
            throw new ProductionWorkerException("MEDIA_JOURNAL_INVALID");
    }
    private static bool Sha(string s) => s.Length == 64 && s.All(c => c is (>= '0' and <= '9') or (>= 'a' and <= 'f'));
}
