using System.Globalization;
using System.Diagnostics;
using System.Reflection;
using System.Reflection.PortableExecutable;
using System.Reflection.Metadata;
using System.Buffers.Binary;
using System.Runtime.Loader;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// #164 phase-1 internal preflight ONLY, in the existing same EXE. This transports
/// assertions, not executable attestation. A Core-issued nonce and ordinary UI
/// Bearer are NOT enrollment, Worker identity, a Claim or GPU authorization.
/// No shipping factory call site: its unconditional proof-required hold remains.
/// </summary>
internal sealed class CoreWorkerChallengeClient : IDisposable
{
    private const string ExpectedDenial = "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED";
    private readonly ControlCenterSession _session;
    private readonly Action _requireCurrentSession;
    private readonly HttpClient _http;
    internal CoreWorkerChallengeClient(ControlCenterSession session, MacCoreClientOptions options, Action requireCurrentSession)
    {
        _session = session; _requireCurrentSession = requireCurrentSession;
        var uri = options.BaseUri;
        if (uri.Scheme is not ("http" or "https") || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0 || uri.AbsolutePath != "/")
            throw Invalid("CORE_CHALLENGE_ENDPOINT_INVALID");
        // Reuse session configuration and token; no second pairing/auth service.
        // Never follow a redirect (including same-origin) with a nonce/signature.
        _http = new(new SocketsHttpHandler
        {
            AllowAutoRedirect = false, UseCookies = false,
            ConnectTimeout = options.ConnectTimeout,
            PooledConnectionLifetime = options.PooledConnectionLifetime,
            MaxConnectionsPerServer = 4,
        }) { BaseAddress = uri, Timeout = Timeout.InfiniteTimeSpan };
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", options.Token);
        _http.DefaultRequestHeaders.Accept.Add(new("application/json"));
        _http.DefaultRequestHeaders.CacheControl = new() { NoStore = true, NoCache = true };
    }

    // A return value describes EXPECTED DENIAL only. Errors/2xx never produce
    // success/admission, and nothing here calls claim, attempt, Comfy or recovery.
    internal async Task<string> RunExpectedDenyAsync(ProductionPlanRecord frozenPlan, string inputRoot,
        string keyRoot, string executorId, string expectedFingerprint, IReadOnlyDictionary<string, string> graphDigests,
        ProductionSubmissionJournal journal, CancellationToken ct)
    {
        // Freeze mutable array/dictionary containers before the first await.
        var plan = JsonSerializer.Deserialize<ProductionPlanRecord>(JsonSerializer.Serialize(frozenPlan))
            ?? throw Invalid("CORE_CHALLENGE_PLAN_INVALID");
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        var digest = Hash(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!));
        var graphs = graphDigests.ToDictionary(p => p.Key, p => p.Value, StringComparer.Ordinal);
        if (plan.SchemaVersion != "1.1" || graphs.Count != plan.Tasks.Length
            || plan.Tasks.Any(t => !graphs.TryGetValue(t.ProductionTaskId, out var graph) || !IsHash(graph) || graph.All(c => c == '0')))
            throw Invalid("CORE_CHALLENGE_GRAPH_SCOPE_INVALID");
        using var executable = await MeasureProcessImageAsync(ct).ConfigureAwait(false);
        var key = ProtectedWorkerSigningKey.Open(keyRoot, executorId, expectedFingerprint);
        _requireCurrentSession();
        using (journal.AcquireGpu()) RequireCleanJournal(journal, plan);
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct);
        budget.CancelAfter(TimeSpan.FromSeconds(30));
        var token = budget.Token;
        var route = "api/v1/production/jobs/" + Uri.EscapeDataString(plan.ProductionJobId);
        using var challengeDocument = await PostAsync(route + "/worker-challenge", new
        { worker_key_id = key.Identity.KeyId, executor_id = executorId, plan_digest = digest }, HttpStatusCode.OK, token).ConfigureAwait(false);
        var challenge = challengeDocument.RootElement;
        ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
        List<DurableReferenceSnapshot> snapshots = [];
        try
        {
            _requireCurrentSession();
            // Prepare and keep the existing crash-persistent copies/pins; no new
            // verifier, cryptography, executor, or journal implementation.
            using (journal.AcquireGpu())
            {
                RequireCleanJournal(journal, plan);
                var store = new ProductionReferenceSnapshotStore(inputRoot, (p, t, d) =>
                    new SessionBoundApproval(new CoreReferenceApprovalSource(_session, p.ProductionJobId, t.ProductionTaskId, d), _requireCurrentSession));
                foreach (var task in plan.Tasks)
                {
                    ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                    snapshots.Add(await store.PrepareAsync(plan, task, digest, graphs[task.ProductionTaskId], journal, token).ConfigureAwait(false));
                }
            }
            _requireCurrentSession();
            ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
            var witness = await BuildWitnessAsync(plan, digest, executorId, key.Identity.KeyId, challenge, snapshots, executable, token).ConfigureAwait(false);
            _requireCurrentSession();
            await executable.RequireCurrentAsync(token).ConfigureAwait(false);
            var unsigned = JsonSerializer.SerializeToElement(witness);
            // Existing signer owns its existing GPU lock, actual file/approval
            // rechecks, DPAPI access and durable spent-nonce marker. Never retry.
            witness["signature"] = await key.SignMeasuredAsync(unsigned, plan, snapshots, journal, DateTimeOffset.UtcNow, token).ConfigureAwait(false);
            using (journal.AcquireGpu())
            {
                _requireCurrentSession();
                RequireCleanJournal(journal, plan);
                ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                foreach (var snapshot in snapshots) await snapshot.RecheckForWitnessAsync(token).ConfigureAwait(false);
                await executable.RequireCurrentAsync(token).ConfigureAwait(false);
                ValidateChallenge(challenge, key.Identity, executorId, plan.ProductionJobId, digest);
                // Retain snapshots + GPU lock through expected-deny POST. Neither
                // this response nor a software signature authorizes production.
                using var response = await PostAsync(route + "/witness/preflight", witness, HttpStatusCode.Conflict, token).ConfigureAwait(false);
                var error = response.RootElement;
                Shape(error, "error");
                var body = error.GetProperty("error");
                Shape(body, "code message retryable trace_id");
                if (body.GetProperty("code").ValueKind != JsonValueKind.String || body.GetProperty("code").GetString() != ExpectedDenial || body.GetProperty("retryable").ValueKind != JsonValueKind.False
                    || body.GetProperty("message").ValueKind != JsonValueKind.String || body.GetProperty("trace_id").ValueKind != JsonValueKind.String)
                    throw Invalid("CORE_PREFLIGHT_DENIAL_UNRECOGNIZED");
                _requireCurrentSession();
                return ExpectedDenial;
            }
        }
        finally { for (var i = snapshots.Count - 1; i >= 0; i--) snapshots[i].Dispose(); }
    }

    private static async Task<JsonObject> BuildWitnessAsync(ProductionPlanRecord plan, string digest, string executor,
        string keyId, JsonElement challenge, IReadOnlyList<DurableReferenceSnapshot> snapshots, ProcessImageMeasurement image, CancellationToken ct)
    {
        var references = plan.Tasks.Select(task =>
        {
            var m = snapshots.Single(s => s.Measurement.TaskId == task.ProductionTaskId).Measurement;
            var r = task.ReferenceAsset ?? throw Invalid("CORE_CHALLENGE_REFERENCE_REQUIRED");
            return new { production_task_id = m.TaskId, shot_id = m.ShotId, asset_id = m.AssetId, approval_id = m.ApprovalId,
                approval_request_digest = r.ApprovalRequestDigest, source_sha256 = m.SourceSha256, source_bytes = m.SourceBytes,
                source_relative_path = r.InputRelativePath, snapshot_sha256 = m.SnapshotSha256, snapshot_bytes = m.SnapshotBytes,
                snapshot_receipt_sha256 = m.ReceiptSha256, graph_digest = m.GraphDigest, snapshot_relative_path = m.SnapshotRelativePath };
        }).ToArray();
        await image.RequireCurrentAsync(ct).ConfigureAwait(false);
        var executable = image.Sha256;
        return JsonSerializer.SerializeToNode(new
        {
            schema_version = "production.worker_witness.v1", algorithm = "ed25519", worker_key_id = keyId, executor_id = executor,
            production_job_id = plan.ProductionJobId, plan_digest = digest, nonce = challenge.GetProperty("nonce").GetString(),
            // Preserve Core's exact UTC microsecond instants; existing codec normalizes bytes.
            issued_at = challenge.GetProperty("issued_at").GetString(), expires_at = challenge.GetProperty("expires_at").GetString(),
            worker_executable_sha256 = executable, journal_digest = Hash("[]"u8.ToArray()), journal_generation = 0,
            journal_state = "NO_PRIOR_POST", references, signature = new string('a', 128),
        })!.AsObject();
    }


    // A local integrity measurement, never a vendor signature or remote attestation.
    // No caller-provided path/hash is accepted by this production entrypoint.
    internal static async Task<ProcessImageMeasurement> MeasureProcessImageAsync(CancellationToken ct)
    {
        var path = CurrentImagePath();
        var image = await OpenExecutableFileAsync(path, ct).ConfigureAwait(false);
        try { await image.RequireCurrentAsync(ct).ConfigureAwait(false); return image; }
        catch { image.Dispose(); throw; }
    }

    private static string CurrentImagePath()
    {
        if (!OperatingSystem.IsWindows()) throw Invalid("WORKER_EXE_WINDOWS_REQUIRED");
        using var process = Process.GetCurrentProcess();
        var buffer = new char[32768]; var size = buffer.Length;
        if (!QueryFullProcessImageNameW(process.SafeHandle, 0, buffer, ref size) || size <= 0 || size > buffer.Length) throw Invalid("WORKER_EXE_OS_PATH_UNVERIFIED");
        var osPath = CanonicalExecutablePath(new string(buffer, 0, size));
        var reported = Environment.ProcessPath;
        if (reported is null || !string.Equals(osPath, CanonicalExecutablePath(reported), StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_PROCESS_PATH_MISMATCH");
        return osPath;
    }

    // Both apphost forms bind the real runtime entry to bytes under the image
    // lease. No Assembly.Location call (or reflective substitute): bundled entry
    // modules have no such file. This is local binding, NOT remote attestation.
    private static void RequireEntryBinding(string path, FileStream image, Assembly? entry, string baseDirectory)
    {
        var name = entry?.GetName().Name;
        if (entry is null || entry.IsDynamic || name is not ("Picotoo Pet AI" or "PicotooPet.MediaWorker.SmokeTests")
            || AssemblyLoadContext.GetLoadContext(entry) != AssemblyLoadContext.Default
            || !string.Equals(System.IO.Path.GetFileName(path), name + ".exe", StringComparison.OrdinalIgnoreCase)
            || !System.IO.Path.IsPathFullyQualified(baseDirectory)
            || !string.Equals(baseDirectory, System.IO.Path.GetFullPath(baseDirectory), StringComparison.OrdinalIgnoreCase)
            || !string.Equals(System.IO.Path.TrimEndingDirectorySeparator(baseDirectory), System.IO.Path.GetDirectoryName(path), StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_HOST_UNVERIFIED");
        // Retain the SDK Win32 resource negative filter, now under the pinned file.
        var original = FileVersionInfo.GetVersionInfo(path).OriginalFilename;
        if (!string.Equals(original, name + ".dll", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(original, name + ".exe", StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_APPHOST_BINDING_UNVERIFIED");
        image.Position = 0;
        int nativeSize;
        using (var pe = new PEReader(image, PEStreamOptions.LeaveOpen))
        {
            nativeSize = pe.PEHeaders.PEHeader?.SizeOfHeaders ?? 0;
            foreach (var section in pe.PEHeaders.SectionHeaders)
            {
                if (section.PointerToRawData < 0 || section.SizeOfRawData < 0) throw Invalid("WORKER_EXE_APPHOST_INVALID");
                nativeSize = Math.Max(nativeSize, checked(section.PointerToRawData + section.SizeOfRawData));
            }
        }
        if (nativeSize <= 0 || nativeSize > 32 * 1024 * 1024 || nativeSize > image.Length) throw Invalid("WORKER_EXE_APPHOST_INVALID");
        image.Position = 0; var native = new byte[nativeSize]; image.ReadExactly(native);
        // .NET HostModel bundle marker; offset zero denotes an ordinary SDK
        // apphost. Search only the bounded native PE, never arbitrary payloads.
        ReadOnlySpan<byte> marker = [0x8b,0x12,0x02,0xb9,0x6a,0x61,0x20,0x38,0x72,0x7b,0x93,0x02,0x14,0xd7,0xa0,0x32,
            0x13,0xf5,0xb9,0xe6,0xef,0xae,0x33,0x18,0xee,0x3b,0x2d,0xce,0x24,0xb3,0x6a,0xae];
        var index = native.AsSpan().IndexOf(marker);
        if (index < 8 || native.AsSpan(index + marker.Length).IndexOf(marker) >= 0
            || native.AsSpan().IndexOf(Encoding.UTF8.GetBytes(name + ".dll\0")) < 0)
            throw Invalid("WORKER_EXE_APPHOST_BINDING_UNVERIFIED");
        var header = BinaryPrimitives.ReadInt64LittleEndian(native.AsSpan(index - 8, 8));
        if (header == 0)
        {
            var dll = System.IO.Path.Combine(baseDirectory, name + ".dll");
            ProductionLocalEnvironment.AssertNoLinkEscape(baseDirectory, dll);
            if (!ProductionLocalEnvironment.IsOrdinaryFile(dll)) throw Invalid("WORKER_EXE_ENTRY_FILE_UNVERIFIED");
            using var file = new FileStream(dll, FileMode.Open, FileAccess.Read, FileShare.Read);
            RequireFinalPath(file.SafeFileHandle, dll); var before = Stamp(file.SafeFileHandle);
            using var pe = new PEReader(file, PEStreamOptions.LeaveOpen);
            RequireEntryMetadata(pe, entry);
            if (before != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_ENTRY_CHANGED");
            RequireFinalPath(file.SafeFileHandle, dll);
            return;
        }
        // Only the actual supported .NET v6.0, uncompressed bundle format is
        // admitted. Unknown formats/flags fail closed, never fall back to a DLL.
        if (header < nativeSize || header >= image.Length || image.Length - header > 1024 * 1024)
            throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        image.Position = header; var manifest = new byte[checked((int)(image.Length - header))]; image.ReadExactly(manifest);
        using var reader = new BinaryReader(new MemoryStream(manifest), new UTF8Encoding(false, true));
        if (reader.ReadUInt32() != 6 || reader.ReadUInt32() != 0) throw Invalid("WORKER_EXE_BUNDLE_VERSION_UNVERIFIED");
        var count = reader.ReadInt32();
        if (count <= 0 || count > 4096) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        _ = ReadBundleName(reader, 128);
        for (var i = 0; i < 2; i++)
        {
            var offset = reader.ReadInt64(); var size = reader.ReadInt64();
            if (offset < nativeSize || size <= 0 || offset > header || size > header - offset) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
        }
        if (reader.ReadUInt64() != 0) throw Invalid("WORKER_EXE_BUNDLE_FLAGS_UNVERIFIED");
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long entryOffset = 0; var entrySize = 0;
        for (var i = 0; i < count; i++)
        {
            var offset = reader.ReadInt64(); var size = reader.ReadInt64(); var compressed = reader.ReadInt64(); var type = reader.ReadByte();
            var relative = ReadBundleName(reader, 1024);
            if (offset < nativeSize || size <= 0 || offset > header || size > header - offset || compressed != 0 || type > 5
                || !names.Add(relative) || relative.Contains(':', StringComparison.Ordinal) || relative.Contains('\\', StringComparison.Ordinal)
                || relative.Split('/').Any(part => part is "" or "." or "..")) throw Invalid("WORKER_EXE_BUNDLE_UNVERIFIED");
            if (relative == name + ".dll")
            {
                if (type != 1 || size > 64 * 1024 * 1024) throw Invalid("WORKER_EXE_BUNDLE_ENTRY_UNVERIFIED");
                entryOffset = offset; entrySize = checked((int)size);
            }
        }
        if (entrySize == 0) throw Invalid("WORKER_EXE_BUNDLE_ENTRY_UNVERIFIED");
        image.Position = entryOffset; var bytes = new byte[entrySize]; image.ReadExactly(bytes);
        using var embedded = new PEReader(new MemoryStream(bytes));
        RequireEntryMetadata(embedded, entry);
    }
    private static string ReadBundleName(BinaryReader reader, int maximum)
    {
        var length = reader.Read7BitEncodedInt();
        if (length <= 0 || length > maximum || length > reader.BaseStream.Length - reader.BaseStream.Position)
            throw Invalid("WORKER_EXE_BUNDLE_STRING_UNVERIFIED");
        return new UTF8Encoding(false, true).GetString(reader.ReadBytes(length));
    }
    private static void RequireEntryMetadata(PEReader pe, Assembly entry)
    {
        if (!pe.HasMetadata) throw Invalid("WORKER_EXE_ENTRY_METADATA_UNVERIFIED");
        var metadata = pe.GetMetadataReader();
        if (!metadata.IsAssembly || metadata.GetString(metadata.GetAssemblyDefinition().Name) != entry.GetName().Name
            || metadata.GetAssemblyDefinition().Version != entry.GetName().Version
            || metadata.GetGuid(metadata.GetModuleDefinition().Mvid) == Guid.Empty
            || metadata.GetGuid(metadata.GetModuleDefinition().Mvid) != entry.ManifestModule.ModuleVersionId)
            throw Invalid("WORKER_EXE_ENTRY_METADATA_UNVERIFIED");
    }
    private static string CanonicalExecutablePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !System.IO.Path.IsPathFullyQualified(path)
            || path.StartsWith(@"\\", StringComparison.Ordinal) || path.Contains('/', StringComparison.Ordinal)
            || path.Length < 4 || path[1] != ':' || path[2] != '\\' || path[3..].Contains(':', StringComparison.Ordinal)
            || !string.Equals(path, System.IO.Path.GetFullPath(path), StringComparison.OrdinalIgnoreCase)
            || !string.Equals(System.IO.Path.GetExtension(path), ".exe", StringComparison.OrdinalIgnoreCase)
            || string.Equals(System.IO.Path.GetFileName(path), "dotnet.exe", StringComparison.OrdinalIgnoreCase))
            throw Invalid("WORKER_EXE_PATH_UNVERIFIED");
        var root = System.IO.Path.GetPathRoot(path)!;
        var drive = new DriveInfo(root);
        // This bounded implementation relies on local NTFS file identity/sharing.
        if (drive.DriveType != DriveType.Fixed || drive.DriveFormat != "NTFS") throw Invalid("WORKER_EXE_FILESYSTEM_UNVERIFIED");
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)) throw Invalid("WORKER_EXE_NOT_ORDINARY");
        return path;
    }
    private static async Task<ProcessImageMeasurement> OpenExecutableFileAsync(string path, CancellationToken ct)
    {
        path = CanonicalExecutablePath(path);
        var parents = new WorkerKeyNamespace(System.IO.Path.GetDirectoryName(path)!);
        FileStream? file = null;
        try
        {
            // Read-only sharing denies writers/deletion while the existing path
            // hasher opens its own read handle. Parent pins deny namespace rename.
            file = new(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            RequireFinalPath(file.SafeFileHandle, path);
            var before = Stamp(file.SafeFileHandle);
            using (var pe = new PEReader(file, PEStreamOptions.LeaveOpen))
            {
                var header = pe.PEHeaders;
                var machine = RuntimeInformation.ProcessArchitecture switch
                {
                    Architecture.X64 => Machine.Amd64, Architecture.X86 => Machine.I386,
                    Architecture.Arm64 => Machine.Arm64, _ => throw Invalid("WORKER_EXE_ARCH_UNSUPPORTED"),
                };
                if (pe.HasMetadata || header.PEHeader is null || header.CoffHeader.Machine != machine
                    || (header.CoffHeader.Characteristics & Characteristics.ExecutableImage) == 0
                    || (header.CoffHeader.Characteristics & Characteristics.Dll) != 0
                    || header.PEHeader.AddressOfEntryPoint <= 0 || header.PEHeader.SizeOfImage <= 0)
                    throw Invalid("WORKER_EXE_NOT_PE_EXECUTABLE");
            }
            if (string.Equals(FileVersionInfo.GetVersionInfo(path).OriginalFilename, "dotnet.exe", StringComparison.OrdinalIgnoreCase))
                throw Invalid("WORKER_EXE_GENERIC_HOST_DENIED");
            var digest = await ProductionLocalEnvironment.Sha256FileAsync(path, ct).ConfigureAwait(false);
            if (before != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_CHANGED");
            RequireFinalPath(file.SafeFileHandle, path);
            return new(path, digest, file, parents, before);
        }
        catch { file?.Dispose(); parents.Dispose(); throw; }
    }

    internal sealed class ProcessImageMeasurement(string path, string digest, FileStream file, WorkerKeyNamespace parents, ImageStamp stamp) : IDisposable
    {
        internal string Path { get; } = path;
        internal string Sha256 { get; } = digest;
        internal async Task RequireCurrentAsync(CancellationToken ct)
        {
            if (!string.Equals(CurrentImagePath(), Path, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_IDENTITY_CHANGED");
            RequireEntryBinding(Path, file, Assembly.GetEntryAssembly(), AppContext.BaseDirectory);
            await VerifyFileAsync(ct).ConfigureAwait(false);
            if (!string.Equals(CurrentImagePath(), Path, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_IDENTITY_CHANGED");
            RequireEntryBinding(Path, file, Assembly.GetEntryAssembly(), AppContext.BaseDirectory);
            ct.ThrowIfCancellationRequested();
        }
        internal async Task VerifyFileAsync(CancellationToken ct)
        {
            CanonicalExecutablePath(Path);
            RequireFinalPath(file.SafeFileHandle, Path);
            if (stamp != Stamp(file.SafeFileHandle)
                || await ProductionLocalEnvironment.Sha256FileAsync(Path, ct).ConfigureAwait(false) != Sha256
                || stamp != Stamp(file.SafeFileHandle)) throw Invalid("WORKER_EXE_CHANGED");
        }
        public void Dispose() { file.Dispose(); parents.Dispose(); }
    }
    internal readonly record struct ImageStamp(uint Volume, uint IdHigh, uint IdLow, uint SizeHigh, uint SizeLow,
        uint CreatedHigh, uint CreatedLow, uint WrittenHigh, uint WrittenLow);
    private static ImageStamp Stamp(SafeFileHandle handle)
    {
        if (!GetFileInformationByHandle(handle, out var info) || info.Links != 1
            || (info.Attributes & 0x410) != 0 || (info.SizeHigh == 0 && info.SizeLow == 0)
            || (info.IdHigh == 0 && info.IdLow == 0)) throw Invalid("WORKER_EXE_FILE_ID_UNVERIFIED");
        return new(info.Volume, info.IdHigh, info.IdLow, info.SizeHigh, info.SizeLow,
            info.Created.High, info.Created.Low, info.Written.High, info.Written.Low);
    }
    private static void RequireFinalPath(SafeFileHandle handle, string expected)
    {
        var name = new char[32768];
        var length = GetFinalPathNameByHandleW(handle, name, (uint)name.Length, 0);
        if (length == 0 || length >= name.Length) throw Invalid("WORKER_EXE_FINAL_PATH_UNVERIFIED");
        var actual = new string(name, 0, checked((int)length));
        if (!actual.StartsWith(@"\\?\", StringComparison.Ordinal)
            || !string.Equals(actual[4..], expected, StringComparison.OrdinalIgnoreCase)) throw Invalid("WORKER_EXE_ALIAS_DENIED");
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeTime { internal uint Low; internal uint High; }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeFileInfo
    {
        internal uint Attributes; internal NativeTime Created; internal NativeTime Accessed; internal NativeTime Written;
        internal uint Volume; internal uint SizeHigh; internal uint SizeLow; internal uint Links; internal uint IdHigh; internal uint IdLow;
    }
#pragma warning disable SYSLIB1054
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, uint flags, [Out] char[] name, ref int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out NativeFileInfo info);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, [Out] char[] name, uint size, uint flags);
#pragma warning restore SYSLIB1054

    private static void RequireCleanJournal(ProductionSubmissionJournal journal, ProductionPlanRecord plan)
    {
        if (journal.Pending().Count != 0 || plan.Tasks.Any(t => journal.Read(plan.ProductionJobId, t.ProductionTaskId) is not null))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
    }
    // Preserve the existing approval authority, but abort if session configuration
    // changes during any of its network awaits, including inside the reused signer.
    private sealed class SessionBoundApproval(ITrustedReferenceApprovalSource source, Action requireCurrent) : ITrustedReferenceApprovalSource
    {
        public async Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken ct)
        {
            requireCurrent();
            var approved = await source.IsApprovedAsync(descriptor, ct).ConfigureAwait(false);
            requireCurrent();
            return approved;
        }
    }
    private static void ValidateChallenge(JsonElement value, WorkerPublicIdentity identity, string executor, string job, string digest)
    {
        Shape(value, "schema_version worker_key_id executor_id production_job_id plan_digest nonce issued_at expires_at");
        if (value.EnumerateObject().Any(p => p.Value.ValueKind != JsonValueKind.String)) throw Invalid("CORE_CHALLENGE_SHAPE_INVALID");
        if (value.GetProperty("schema_version").GetString() != "production.worker_challenge.v1"
            || value.GetProperty("worker_key_id").GetString() != identity.KeyId || value.GetProperty("executor_id").GetString() != executor
            || value.GetProperty("production_job_id").GetString() != job || value.GetProperty("plan_digest").GetString() != digest
            || Hash(Convert.FromHexString(identity.PublicKeyHex)) != identity.Fingerprint || identity.KeyId != "wk-" + identity.Fingerprint[..40])
            throw Invalid("CORE_CHALLENGE_SCOPE_MISMATCH");
        var nonce = value.GetProperty("nonce").GetString();
        if (nonce is null || !IsHash(nonce) || nonce.All(c => c == '0')) throw Invalid("CORE_CHALLENGE_NONCE_INVALID");
        var issued = Utc(value.GetProperty("issued_at")); var expires = Utc(value.GetProperty("expires_at")); var now = DateTimeOffset.UtcNow;
        if (expires <= issued || expires - issued > TimeSpan.FromSeconds(30) || issued > now.AddSeconds(5) || expires <= now)
            throw Invalid("CORE_CHALLENGE_EXPIRED_OR_INVALID");
    }
    private static DateTimeOffset Utc(JsonElement value)
    {
        var text = value.GetString();
        if (text is null || text.Length > 40 || !Regex.IsMatch(text, @"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$", RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(100))
            || !DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) || date.Offset != TimeSpan.Zero)
            throw Invalid("CORE_CHALLENGE_UTC_REQUIRED");
        return date;
    }
    private async Task<JsonDocument> PostAsync(string route, object payload, HttpStatusCode expected, CancellationToken ct)
    {
        _requireCurrentSession();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(10));
        using var request = new HttpRequestMessage(HttpMethod.Post, route) { Content = JsonContent.Create(payload) };
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false);
        if (response.StatusCode != expected) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_UNEXPECTED_STATUS");
        if (response.Content.Headers.ContentType?.MediaType != "application/json" || response.Content.Headers.ContentLength > 16384)
            throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_RESPONSE_INVALID");
        using var stream = await response.Content.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false);
        using var bytes = new MemoryStream();
        var buffer = new byte[4096]; int read;
        while ((read = await stream.ReadAsync(buffer, deadline.Token).ConfigureAwait(false)) != 0)
        {
            if (bytes.Length + read > 16384) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_RESPONSE_TOO_LARGE");
            bytes.Write(buffer, 0, read);
        }
        _requireCurrentSession();
        return JsonDocument.Parse(bytes.ToArray(), new() { MaxDepth = 16 });
    }
    private static void Shape(JsonElement value, string names)
    {
        if (value.ValueKind != JsonValueKind.Object) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
        var expected = names.Split(' ').ToHashSet(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject()) if (!expected.Remove(property.Name)) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
        if (expected.Count != 0) throw Invalid("CORE_CHALLENGE_OR_PREFLIGHT_SHAPE_INVALID");
    }
    private static bool IsHash(string text) => text.Length == 64 && text.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static InvalidDataException Invalid(string code) => new(code); // Never log response bodies, Bearer, nonce or seed.
    public void Dispose() => _http.Dispose();
}
