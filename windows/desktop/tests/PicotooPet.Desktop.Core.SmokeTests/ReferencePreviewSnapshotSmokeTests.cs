using System.Security.Cryptography;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class ReferencePreviewSnapshotSmokeTests
{
    public static async Task RunAsync()
    {
        var workspace = Path.Combine(Path.GetTempPath(), "p0-preview-stage-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(workspace);
        var root = Path.Combine(workspace, "input");
        Directory.CreateDirectory(root);
        var source = Path.Combine(workspace, "source.png");
        var bytes = PngBytes();
        await File.WriteAllBytesAsync(source, bytes).ConfigureAwait(false);
        var policy = new ReferencePreviewFilePolicy(ProductionLocalEnvironment.ResolveUnderRoot,
            ProductionLocalEnvironment.AssertNoLinkEscape, ProductionLocalEnvironment.IsOrdinaryFile,
            ProductionLocalEnvironment.Sha256FileAsync);
        var stager = new ReferencePreviewSnapshotStager(root, policy, ReferenceBatchPreviewViewModel.ValidateImageAsync);
        try
        {
            var snapshot = await stager.StageAsync(source, "shot-1").ConfigureAwait(false);
            var expectedSha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            SmokeAssert.Equal(expectedSha, snapshot.Sha256, "actual image-byte SHA, not manifest SHA");
            SmokeAssert.Equal((long)bytes.Length, snapshot.Bytes, "actual image length");
            SmokeAssert.Equal($"PicotooPet/references/{expectedSha}/shot-1.png", snapshot.InputRelativePath, "content addressed managed shot path");
            var managed = Path.Combine(root, snapshot.InputRelativePath.Replace('/', Path.DirectorySeparatorChar));
            SmokeAssert.True((File.GetAttributes(managed) & FileAttributes.ReadOnly) != 0, "durable read-only accident protection");
            SmokeAssert.True((await stager.ReadVerifiedAsync(snapshot).ConfigureAwait(false)).SequenceEqual(bytes), "managed bytes equal preview");
            var repeat = await stager.StageAsync(source, "shot-1").ConfigureAwait(false);
            SmokeAssert.Equal(snapshot, repeat, "same bytes/shot produce stable snapshot across retries");
            var secondShot = await stager.StageAsync(source, "shot-2").ConfigureAwait(false);
            SmokeAssert.True(secondShot.InputRelativePath != snapshot.InputRelativePath, "Core requires distinct paths for distinct shots");

            await File.WriteAllTextAsync(source, "not an image").ConfigureAwait(false);
            SmokeAssert.True((await stager.ReadVerifiedAsync(snapshot).ConfigureAwait(false)).SequenceEqual(bytes), "original selection replacement cannot change managed preview");
            await RejectAsync(() => stager.StageAsync(source, "shot-3"), "fake PNG rejected by real decoder").ConfigureAwait(false);
            await File.WriteAllBytesAsync(source, bytes).ConfigureAwait(false);
            var huge = Path.Combine(workspace, "huge.png");
            using (var file = new FileStream(huge, FileMode.CreateNew, FileAccess.Write)) file.SetLength(ReferencePreviewSnapshotStager.MaxBytes + 1L);
            await RejectAsync(() => stager.StageAsync(huge, "shot-3"), "32MiB bound before allocation").ConfigureAwait(false);
            foreach (var shot in new[] { "..", "../escape", "shot:stream", "shot/3", "shot " })
                await RejectAsync(() => stager.StageAsync(source, shot), "shot path injection").ConfigureAwait(false);
            var svg = Path.Combine(workspace, "unsafe.svg");
            await File.WriteAllBytesAsync(svg, bytes).ConfigureAwait(false);
            await RejectAsync(() => stager.StageAsync(svg, "shot-3"), "unsupported type").ConfigureAwait(false);
            await RejectAsync(() => stager.StageAsync(Path.Combine(workspace, "missing.png"), "shot-3"), "missing source").ConfigureAwait(false);

            File.SetAttributes(managed, FileAttributes.Normal);
            await File.WriteAllTextAsync(managed, "tampered snapshot").ConfigureAwait(false);
            var restarted = new ReferencePreviewSnapshotStager(root, policy, ReferenceBatchPreviewViewModel.ValidateImageAsync);
            await RejectAsync(() => restarted.ReadVerifiedAsync(snapshot), "restart must rehash tampered snapshot").ConfigureAwait(false);
            await RejectAsync(() => restarted.StageAsync(source, "shot-1"), "do not overwrite/reapprove corrupt CAS occupant").ConfigureAwait(false);
            await RejectAsync(() => restarted.ReadVerifiedAsync(snapshot with { InputRelativePath = "../source.png" }), "managed snapshot path escape").ConfigureAwait(false);
            Console.WriteLine("REFERENCE_PREVIEW_SNAPSHOT=PASS; SYNTHETIC_IMAGE_ONLY; GPU_POST=0");
        }
        finally
        {
            // Only this test's explicit random temp directory; remove read-only synthetic files.
            foreach (var file in Directory.EnumerateFiles(workspace, "*", SearchOption.AllDirectories)) File.SetAttributes(file, FileAttributes.Normal);
            Directory.Delete(workspace, recursive: true);
        }
    }

    internal static byte[] PngBytes()
    {
        var image = BitmapSource.Create(1, 1, 96, 96, PixelFormats.Bgra32, null, new byte[] { 0, 0, 255, 255 }, 4);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(image));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        return stream.ToArray();
    }

    private static async Task RejectAsync<T>(Func<Task<T>> action, string reason)
    {
        try { _ = await action().ConfigureAwait(false); }
        catch (Exception error) when (error is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException) { return; }
        throw new InvalidOperationException("Expected rejection: " + reason);
    }
}
