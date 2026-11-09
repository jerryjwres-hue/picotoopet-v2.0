using System.Text.Json;
using System.Text.Json.Serialization;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>
/// Result of trying to open the production Owner Review path. <see cref="Client"/> is non-null only
/// when every lock below opened; otherwise <see cref="LockCode"/> is a stable fail-closed reason.
/// The caller owns (and must dispose) a non-null client.
/// </summary>
public sealed record OwnerReviewLiveResult(OwnerReviewClient? Client, string LockCode)
{
    public bool IsOpen => Client is not null;

    internal static OwnerReviewLiveResult Locked(string code) => new(null, code);
}

/// <summary>
/// The single production entry that turns the (default locked) Owner Review UI into a live one.
/// Locks, in order; the first closed lock stops everything and nothing else is read or started:
/// 1. the compile-time gate <see cref="OwnerReviewTransportGate.PinnedSshStdioActivated"/> (activation token);
/// 2. an owner-authored, NTFS-protected profile file (strict JSON, no unknown fields);
/// 3. the typed factory <see cref="OwnerReviewClient.CreatePinnedSshStdio"/>, which verifies the pinned
///    host key and the protected key/known_hosts files before any process exists.
/// No Mock/plain HTTP/injected handler is possible here. The credential is NOT read here: the separate
/// OwnerPrincipal credential store is consulted per request, so a missing OwnerPrincipal credential still
/// refuses every operation. Worker Ed25519/DPAPI identities and the device token are never touched.
/// </summary>
public static class OwnerReviewLiveWiring
{
    public const string ProfileFileName = "owner_review_live_profile.json";
    public const string PrivateKeyFileName = "owner_review_windows_client_ed25519";
    public const string KnownHostsFileName = "known_hosts_owner_review_mac";
    public const string NotWindowsCode = "OWNER_REVIEW_LIVE_PLATFORM_UNSUPPORTED";
    public const string ProfileInvalidCode = "OWNER_REVIEW_LIVE_PROFILE_INVALID";
    public const string ProfileMissingCode = "OWNER_REVIEW_LIVE_PROFILE_MISSING";
    public const string ProfileUnreadableCode = "OWNER_REVIEW_LIVE_PROFILE_UNREADABLE";

    private const int MaxProfileBytes = 4096;

    private static readonly JsonSerializerOptions StrictJson = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        AllowTrailingCommas = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
    };

    /// <summary>Default private directory shared with the protected key and pinned known_hosts.</summary>
    public static string DefaultDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPet",
        "OwnerReviewSsh");

    /// <summary>Production entry. Stays locked while the gate constant is false.</summary>
    public static OwnerReviewLiveResult TryOpen(IOwnerReviewCredentialStore credentials) =>
        TryOpen(OwnerReviewSshStdioActivation.TryGetProductionActivation(), DefaultDirectory, credentials);

    internal static OwnerReviewLiveResult TryOpen(
        OwnerReviewSshStdioActivation? activation,
        string directory,
        IOwnerReviewCredentialStore credentials)
    {
        ArgumentNullException.ThrowIfNull(credentials);
        if (activation is null)
        {
            // First lock: nothing on disk is even looked at.
            return OwnerReviewLiveResult.Locked("OWNER_REVIEW_SSH_STDIO_NOT_ACTIVATED");
        }
        if (!OperatingSystem.IsWindows())
        {
            return OwnerReviewLiveResult.Locked(NotWindowsCode);
        }

        try
        {
            var profile = LoadProfile(directory);
            return new OwnerReviewLiveResult(
                OwnerReviewClient.CreatePinnedSshStdio(profile, credentials, activation),
                string.Empty);
        }
        catch (OwnerReviewException error)
        {
            return OwnerReviewLiveResult.Locked(error.Code);
        }
        catch (Exception error) when (error is IOException
            or UnauthorizedAccessException
            or System.Security.SecurityException
            or NotSupportedException
            or ArgumentException
            or InvalidOperationException)
        {
            // Protected-file I/O must never escape into the UI click path.
            return OwnerReviewLiveResult.Locked(ProfileUnreadableCode);
        }
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private static OwnerReviewSshStdioProfile LoadProfile(string directory)
    {
        if (string.IsNullOrWhiteSpace(directory) || !Path.IsPathFullyQualified(directory))
        {
            throw Blocked(ProfileInvalidCode);
        }
        var file = Path.Combine(directory, ProfileFileName);
        if (!File.Exists(file))
        {
            throw Blocked(ProfileMissingCode);
        }
        if ((File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0)
        {
            throw Blocked(ProfileInvalidCode);
        }
        // The profile decides which host the owner credential is sent to: it must be as protected
        // as the key and known_hosts it points at (owner/DACL of the file and its directory).
        OwnerReviewProtectedFileAcl.Require(file);

        var bytes = File.ReadAllBytes(file);
        if (bytes.Length is 0 or > MaxProfileBytes)
        {
            throw Blocked(ProfileInvalidCode);
        }
        LiveProfileFile? document;
        try
        {
            document = JsonSerializer.Deserialize<LiveProfileFile>(bytes, StrictJson);
        }
        catch (JsonException)
        {
            throw Blocked(ProfileInvalidCode);
        }
        if (document is null
            || document.SchemaVersion != "owner_review_live_profile.v1"
            || string.IsNullOrWhiteSpace(document.MacHost)
            || string.IsNullOrWhiteSpace(document.MacUser)
            || string.IsNullOrWhiteSpace(document.ExpectedHostKeyFingerprint))
        {
            throw Blocked(ProfileInvalidCode);
        }
        // Key and known_hosts live at fixed names beside the profile; the profile cannot redirect them.
        return new OwnerReviewSshStdioProfile(
            document.MacHost,
            document.MacUser,
            document.SshPort,
            document.CorePort,
            Path.Combine(directory, KnownHostsFileName),
            document.ExpectedHostKeyFingerprint,
            Path.Combine(directory, PrivateKeyFileName));
    }

    private static OwnerReviewException Blocked(string code) =>
        new(OwnerReviewFailureKind.TransportBlocked, 0, code);

    private sealed record LiveProfileFile(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("mac_host")] string MacHost,
        [property: JsonPropertyName("mac_user")] string MacUser,
        [property: JsonPropertyName("ssh_port")] int SshPort,
        [property: JsonPropertyName("core_port")] int CorePort,
        [property: JsonPropertyName("expected_host_key_fingerprint")] string ExpectedHostKeyFingerprint);
}
