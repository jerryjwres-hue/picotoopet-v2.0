using System.ComponentModel;
using System.Diagnostics;
using System.Net.Http;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>
/// 独立 SSH -W 候选：每条 HTTP 连接是一条受主机密钥约束的 OpenSSH 进程管道。
/// 不启动本地 TCP listener、不读取 Owner Bearer、不激活现有 OwnerReviewClient。
/// </summary>
public static class OwnerReviewSshStdioCandidate
{
    public static readonly Uri SyntheticAuthority = new(
        "http://" + OwnerReviewSshStdioProfileVerifier.InternalHttpHost + "/");

    /// <summary>
    /// 构造尚未生产接线的候选 Handler；无主机密钥 pin 即失败。
    /// HTTP 明文只在本进程管道内传递，实际网络传输由 ssh -W 加密。
    /// </summary>
    public static SocketsHttpHandler CreateIsolatedHandler(OwnerReviewSshStdioProfile profile)
    {
        // 预检必须发生在构造时，也必须在每次建连时重新检查。
        _ = OwnerReviewSshStdioProfileVerifier.BuildPinnedCommand(profile);
        return new SocketsHttpHandler
        {
            UseProxy = false,
            AllowAutoRedirect = false,
            AutomaticDecompression = System.Net.DecompressionMethods.None,
            ConnectTimeout = TimeSpan.FromSeconds(12),
            PooledConnectionLifetime = TimeSpan.FromSeconds(30),
            PooledConnectionIdleTimeout = TimeSpan.FromSeconds(5),
            MaxConnectionsPerServer = 1,
            ConnectCallback = (context, cancellationToken) =>
                OpenPinnedStdioAsync(profile, context, cancellationToken),
        };
    }

    /// <summary>拒绝错误 URI，避免 Handler 被用于设备令牌、普通外网或任意 Core 地址。</summary>
    private static ValueTask<Stream> OpenPinnedStdioAsync(
        OwnerReviewSshStdioProfile profile,
        SocketsHttpConnectionContext context,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (context.DnsEndPoint.Host != OwnerReviewSshStdioProfileVerifier.InternalHttpHost
            || context.DnsEndPoint.Port != 80)
        {
            throw new OwnerReviewException(
                OwnerReviewFailureKind.TransportBlocked, 0, "OWNER_REVIEW_SSH_ENDPOINT_MISMATCH");
        }
        var start = OwnerReviewSshStdioProfileVerifier.BuildPinnedCommand(profile);
        var process = new Process { StartInfo = start };
        try
        {
            if (!process.Start())
            {
                throw new IOException("OWNER_REVIEW_SSH_PROCESS_NOT_STARTED");
            }

            // 丢弃并持续排空 stderr：避免缓冲死锁和错误输出中的主机资料泄漏。
            // 失败时 stdout 会关闭，HTTP 层必须失败关闭，不能尝试直接 TCP。
            _ = DrainStderrAsync(process.StandardError.BaseStream);
            return ValueTask.FromResult<Stream>(new SshStdioDuplexStream(process));
        }
        catch (Exception error) when (error is IOException or Win32Exception or InvalidOperationException)
        {
            try
            {
                if (!process.HasExited) process.Kill(entireProcessTree: true);
            }
            catch (InvalidOperationException)
            {
                // 进程已退出；不把 SSH 错误内容传播到 UI 或日志。
            }
            finally
            {
                process.Dispose();
            }
            throw new OwnerReviewException(
                OwnerReviewFailureKind.Unavailable, 0, "OWNER_REVIEW_SSH_PROCESS_UNAVAILABLE");
        }
    }

    private static async Task DrainStderrAsync(Stream stderr)
    {
        try
        {
            await stderr.CopyToAsync(Stream.Null).ConfigureAwait(false);
        }
        catch (IOException)
        {
            // 进程退出或取消连接，不升级权限、不重试明文路径。
        }
        catch (ObjectDisposedException)
        {
            // 同上。错误输出永不保留。
        }
    }

    /// <summary>完整双向进程管道；断开即关闭 SSH，不留下本地监听者。</summary>
    private sealed class SshStdioDuplexStream(Process process) : Stream
    {
        private readonly Stream _input = process.StandardInput.BaseStream;
        private readonly Stream _output = process.StandardOutput.BaseStream;
        private int _disposed;

        public override bool CanRead => _disposed == 0;
        public override bool CanSeek => false;
        public override bool CanWrite => _disposed == 0;
        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count) =>
            _output.Read(buffer, offset, count);

        public override ValueTask<int> ReadAsync(
            Memory<byte> buffer, CancellationToken cancellationToken = default) =>
            _output.ReadAsync(buffer, cancellationToken);

        public override void Write(byte[] buffer, int offset, int count) =>
            _input.Write(buffer, offset, count);

        public override ValueTask WriteAsync(
            ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default) =>
            _input.WriteAsync(buffer, cancellationToken);

        public override void Flush() => _input.Flush();
        public override Task FlushAsync(CancellationToken cancellationToken) =>
            _input.FlushAsync(cancellationToken);

        public override long Seek(long offset, SeekOrigin origin) =>
            throw new NotSupportedException();

        public override void SetLength(long value) =>
            throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposing && Interlocked.Exchange(ref _disposed, 1) == 0)
            {
                try
                {
                    _input.Dispose();
                    _output.Dispose();
                    if (!process.HasExited)
                    {
                        process.Kill(entireProcessTree: true);
                    }
                }
                catch (InvalidOperationException)
                {
                    // SSH 已自然退出，关闭连接无须重新启动。
                }
                catch (IOException)
                {
                    // 关闭管道时允许对端已经退出；不回退到普通 HTTP。
                }
                finally
                {
                    process.Dispose();
                }
            }
            base.Dispose(disposing: disposing);
        }

        public override ValueTask DisposeAsync()
        {
            Dispose();
            // CA2215: 即使已关闭 SSH 管道，仍须执行 Stream 基类释放逻辑。
            return base.DisposeAsync();
        }
    }
}
