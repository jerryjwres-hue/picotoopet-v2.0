using System.Text.Json;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>Explicit local public-fingerprint binding; Core independently enrolls its trust model.</summary>
internal sealed record WorkerLocalPairing(string Fingerprint)
{
    internal static string KeyRoot => Path.Combine(ProductionSubmissionJournal.DefaultRoot, "worker-signing");
    private static string BindingPath => Path.Combine(KeyRoot, "pairing.json");
    internal static WorkerPublicIdentity Initialize(string executor)
    {
        // Validate/create the existing journal namespace with its existing link checks.
        using var gpu = new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot).AcquireGpu();
        var identity = ProtectedWorkerSigningKey.Create(KeyRoot, executor);
        using var file = new FileStream(Path.Combine(KeyRoot, "public-identity.json"), FileMode.CreateNew,
            FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough);
        file.Write(JsonSerializer.SerializeToUtf8Bytes(identity));
        file.Flush(true);
        return identity;
    }
    internal static void Bind(string executor, string fingerprint)
    {
        var identity = ProtectedWorkerSigningKey.Open(KeyRoot, executor, fingerprint).Identity;
        using var file = new FileStream(BindingPath, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough);
        file.Write(JsonSerializer.SerializeToUtf8Bytes(new WorkerLocalPairing(identity.Fingerprint)));
        file.Flush(true);
    }
    internal static WorkerLocalPairing Require(string executor)
    {
        try
        {
            if (!File.Exists(BindingPath) || (File.GetAttributes(BindingPath) & FileAttributes.ReparsePoint) != 0)
                throw new IOException();
            using var file = new FileStream(BindingPath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (file.Length is <= 0 or > 512) throw new IOException();
            using var document = JsonDocument.Parse(file);
            var value = document.RootElement;
            if (value.ValueKind != JsonValueKind.Object || value.EnumerateObject().Count() != 1
                || !value.TryGetProperty(nameof(Fingerprint), out var fingerprint) || fingerprint.ValueKind != JsonValueKind.String)
                throw new IOException();
            var text = fingerprint.GetString()!;
            if (text.Length != 64 || text.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
                throw new IOException();
            _ = ProtectedWorkerSigningKey.Open(KeyRoot, executor, text);
            return new(text);
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            throw new ProductionWorkerException("I2V_CROSS_ENDPOINT_WORKER_PROOF_REQUIRED");
        }
    }
}
