using System.Runtime.Versioning;
using System.Security;
using System.Security.AccessControl;
using System.Security.Principal;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>
/// Fail-closed effective NTFS owner/DACL gate for the SSH client private key, the pinned
/// known_hosts file and their immediate parent directory. It only reads security descriptors;
/// it never reads file contents, never changes permissions and never prints key material.
/// </summary>
/// <summary>Stable fail-closed codes of the protected-file gate (platform neutral).</summary>
public static class OwnerReviewProtectedFileAclCodes
{
    public const string TooBroad = "OWNER_REVIEW_SSH_PROTECTED_FILE_ACL_TOO_BROAD";
    public const string Unverified = "OWNER_REVIEW_SSH_PROTECTED_FILE_ACL_UNVERIFIED";
}

[SupportedOSPlatform("windows")]
public static class OwnerReviewProtectedFileAcl
{

    /// <summary>Verifies the file and its parent directory for the current Windows user.</summary>
    public static void Require(string filePath)
    {
        var user = WindowsIdentity.GetCurrent().User ?? throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
        Require(filePath, user);
    }

    internal static void Require(string filePath, SecurityIdentifier currentUser)
    {
        ArgumentNullException.ThrowIfNull(currentUser);
        if (string.IsNullOrWhiteSpace(filePath) || !Path.IsPathFullyQualified(filePath))
        {
            throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
        }
        try
        {
            var file = new FileInfo(filePath);
            var directory = file.Directory ?? throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
            if (!file.Exists
                || (file.Attributes & FileAttributes.ReparsePoint) != 0
                || (directory.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
            }
            RequireProtected(
                file.GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access),
                currentUser);
            RequireProtected(
                directory.GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access),
                currentUser);
        }
        catch (Exception error) when (error is IOException
            or UnauthorizedAccessException
            or InvalidOperationException
            or ArgumentException
            or PlatformNotSupportedException
            or SecurityException)
        {
            throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
        }
    }

    internal static void RequireProtected(FileSystemSecurity security, SecurityIdentifier currentUser)
    {
        if (security.GetOwner(typeof(SecurityIdentifier)) is not SecurityIdentifier owner
            || !IsAllowedPrincipal(owner, currentUser))
        {
            throw Blocked(OwnerReviewProtectedFileAclCodes.TooBroad);
        }

        var descriptor = new RawSecurityDescriptor(security.GetSecurityDescriptorBinaryForm(), 0);
        // A null DACL grants all access; a present zero-ACE DACL denies all access.
        // Neither is a verified, usable SSH client ACL, so both must fail closed.
        var dacl = descriptor.DiscretionaryAcl ?? throw Blocked(OwnerReviewProtectedFileAclCodes.TooBroad);
        if (dacl.Count == 0)
        {
            throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
        }
        foreach (var ace in dacl)
        {
            if (ace is not QualifiedAce qualified)
            {
                throw Blocked(OwnerReviewProtectedFileAclCodes.Unverified);
            }
            if (qualified.AceQualifier == AceQualifier.AccessAllowed
                && !IsAllowedPrincipal(qualified.SecurityIdentifier, currentUser))
            {
                throw Blocked(OwnerReviewProtectedFileAclCodes.TooBroad);
            }
        }
    }

    private static bool IsAllowedPrincipal(SecurityIdentifier sid, SecurityIdentifier currentUser) =>
        sid.Equals(currentUser)
        || sid.IsWellKnown(WellKnownSidType.LocalSystemSid)
        || sid.IsWellKnown(WellKnownSidType.BuiltinAdministratorsSid);

    private static OwnerReviewException Blocked(string code) =>
        new(OwnerReviewFailureKind.TransportBlocked, 0, code);
}
