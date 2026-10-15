using System.Diagnostics;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>
/// C009B hardening v1 的安全负例：路径策略、WAV 有界/畸形、输入句柄 TOCTOU 保护。
/// 真实文件系统 + 真实 composer，仅进程边界为假（Kill/排空语义见 RealHardening）。
/// </summary>
internal static class HardeningTests
{
    public static async Task RunAsync()
    {
        await AdversarialPathsRejectedWithoutIoAsync().ConfigureAwait(false);
        await LegitimateLocalPathsAcceptedAsync().ConfigureAwait(false);
        await ReparseParentAndLeafRejectedAsync().ConfigureAwait(false);
        await WavBoundsAndMalformedHeadersAsync().ConfigureAwait(false);
        await HeldHandlesBlockReplacementAsync().ConfigureAwait(false);
        PolicyTableDirect();
    }

    // ── 路径策略 ───────────────────────────────────────────────────────────────────────────
    private static readonly string[] AdversarialPaths =
    [
        @"\\attacker-host\share\a.wav",
        @"\\attacker-host\share\master.mp4",
        @"\\?\C:\Windows\Temp\a.wav",
        @"\\.\pipe\evil",
        @"\\.\C:\x\a.wav",
        "//attacker-host/share/a.wav",
        @"\a.wav",
        @"\Windows\Temp\a.wav",
        @"C:a.wav",
        @"relative\a.wav",
        "a.wav",
        @"C:\x\..\a.wav",
        @"C:\x\.\a.wav",
        @"C:\x\a.wav:evil",
        @"C:\x\CON",
        @"C:\x\nul.wav",
        @"C:\x\COM1.txt",
        "C:\\x\\a.wav ",
        "C:\\x\\a.wav.",
        "C:\\x\\a?.wav",
        "C:\\x\\a*.wav",
        "C:\\x\\a|b.wav",
        "C:\\x\\a\0b.wav",
        "C:\\x\\a\nb.wav",
        "",
        "   ",
    ];

    private static async Task AdversarialPathsRejectedWithoutIoAsync()
    {
        foreach (var bad in AdversarialPaths)
        {
            using var env = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
            var requests = new (string Target, MasterVideoCompositionRequest Request)[]
            {
                ("visual", env.Request() with { Visual = env.Visual with { Path = bad } }),
                ("output", env.Request() with { OutputPath = bad }),
                ("wav", env.Request(segments: [env.Segments[0] with { WavPath = bad }])),
            };
            foreach (var (target, request) in requests)
            {
                var clock = Stopwatch.StartNew();
                var expected = string.IsNullOrWhiteSpace(bad) && target != "wav"
                    ? MasterVideoComposerException.RequestInvalid
                    : MasterVideoComposerException.PathInvalid;
                try
                {
                    await new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(request, CancellationToken.None)
                        .ConfigureAwait(false);
                    throw new InvalidOperationException($"对抗路径必须拒绝：{target}");
                }
                catch (MasterVideoComposerException exception)
                {
                    // 空白路径在更早的形状检查被拒绝；其余全部必须是 PATH_INVALID。
                    Check.True(
                        exception.Code == expected
                        || (string.IsNullOrWhiteSpace(bad) && exception.Code is MasterVideoComposerException.NarrationInvalid
                            or MasterVideoComposerException.PathInvalid),
                        $"{target}: 错误码 {exception.Code}");
                    Check.True(!exception.Message.Contains("attacker-host", StringComparison.Ordinal), "错误不得回显路径");
                }
                Check.True(clock.ElapsedMilliseconds < 2000, $"{target}: 拒绝必须是纯字符串检查，不得触发网络/设备 I/O");
                Check.Equal(0, env.Runner.Calls.Count, $"{target}: 不得启动进程");
                Check.True(!File.Exists(env.OutputPath), $"{target}: 不得写输出");
            }
        }
    }

    private static async Task LegitimateLocalPathsAcceptedAsync()
    {
        // 空格、括号与中文目录名是合法本地路径，必须保持可用。
        using var unicode = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)], " dir (测试) x");
        await new FixedFfmpegMasterVideoComposer(unicode.Runner).ComposeAsync(unicode.Request(), CancellationToken.None)
            .ConfigureAwait(false);
        Check.True(File.Exists(unicode.OutputPath), "含空格/括号/中文的本地路径必须可用");

        // 正斜杠的本地完全限定路径同样可用。
        using var slashes = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
        var forward = slashes.Request() with
        {
            Visual = slashes.Visual with { Path = slashes.Visual.Path.Replace('\\', '/') },
            OutputPath = slashes.OutputPath.Replace('\\', '/'),
            NarrationSegments = [slashes.Segments[0] with { WavPath = slashes.Segments[0].WavPath.Replace('\\', '/') }],
        };
        await new FixedFfmpegMasterVideoComposer(slashes.Runner).ComposeAsync(forward, CancellationToken.None)
            .ConfigureAwait(false);
        Check.True(File.Exists(slashes.OutputPath), "正斜杠本地路径必须可用");

        // 小写盘符同样可用。
        using var lower = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
        var lowered = lower.Request() with
        {
            Visual = lower.Visual with { Path = char.ToLowerInvariant(lower.Visual.Path[0]) + lower.Visual.Path[1..] },
        };
        await new FixedFfmpegMasterVideoComposer(lower.Runner).ComposeAsync(lowered, CancellationToken.None)
            .ConfigureAwait(false);
        Check.True(File.Exists(lower.OutputPath), "小写盘符本地路径必须可用");

        // 复用 Visual/输出/其他 WAV 路径被拒绝（重复指向同一文件）。
        using var alias = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(alias.Runner).ComposeAsync(
                alias.Request(segments: [alias.Segments[0] with { WavPath = alias.Visual.Path }]), CancellationToken.None),
            MasterVideoComposerException.PathInvalid,
            "WAV 指向视觉文件必须拒绝").ConfigureAwait(false);
    }

    private static void PolicyTableDirect()
    {
        foreach (var good in new[] { @"C:\a\b.wav", "D:/a/b.wav", @"c:\a b\(x)\测试.wav", @"Z:\a\b" })
        {
            Check.True(MasterVideoPathPolicy.IsSafeLocalFullyQualified(good), $"合法：{good}");
        }
        foreach (var bad in AdversarialPaths)
        {
            Check.True(!MasterVideoPathPolicy.IsSafeLocalFullyQualified(bad), $"非法：{bad}");
        }
        Check.True(!MasterVideoPathPolicy.IsSafeLocalFullyQualified(null), "null 非法");
        Check.True(!MasterVideoPathPolicy.IsSafeLocalFullyQualified(@"C:\" + new string('a', 5000)), "超长路径非法");
    }

    // ── 重解析点：父目录 / 叶文件 ──────────────────────────────────────────────────────────────
    private static async Task ReparseParentAndLeafRejectedAsync()
    {
        using var env = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
        var realDirectory = Path.GetDirectoryName(env.Visual.Path)!;
        var linkDirectory = Path.Combine(Path.GetDirectoryName(realDirectory)!, "visual-link");
        try
        {
            Directory.CreateSymbolicLink(linkDirectory, realDirectory);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            Console.WriteLine("MASTER_MUX_HARDENING_REPARSE=UNVERIFIED(symlink privilege unavailable)");
            return;
        }
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(
                env.Request() with { Visual = env.Visual with { Path = Path.Combine(linkDirectory, "visual.mp4") } },
                CancellationToken.None),
            MasterVideoComposerException.PathInvalid,
            "父目录为符号链接必须拒绝").ConfigureAwait(false);
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(
                env.Request(segments: [env.Segments[0] with { WavPath = Path.Combine(linkDirectory, "seg1.wav") }]),
                CancellationToken.None),
            MasterVideoComposerException.PathInvalid,
            "WAV 父目录为符号链接必须拒绝").ConfigureAwait(false);

        var leaf = Path.Combine(realDirectory, "visual-leaf.mp4");
        File.CreateSymbolicLink(leaf, env.Visual.Path);
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(
                env.Request() with { Visual = env.Visual with { Path = leaf } }, CancellationToken.None),
            MasterVideoComposerException.VisualInvalid,
            "叶文件为符号链接必须拒绝").ConfigureAwait(false);
        Check.Equal(0, env.Runner.Calls.Count, "链接拒绝不得启动进程");
        Check.True(!File.Exists(env.OutputPath), "链接拒绝不得写输出");
    }

    // ── WAV 有界读取与畸形头部 ──────────────────────────────────────────────────────────────
    private static async Task WavBoundsAndMalformedHeadersAsync()
    {
        // 声明的字节数超过冻结的 C009A 上限（32 MiB）：在任何 I/O 之前拒绝。
        using (var over = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]))
        {
            var oversized = over.Segments[0] with { Bytes = FixedFfmpegMasterVideoComposer.MaximumWavBytes + 1 };
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(over.Runner)
                    .ComposeAsync(over.Request(segments: [oversized]), CancellationToken.None),
                MasterVideoComposerException.NarrationInvalid,
                "超过单个 WAV 上限必须拒绝").ConfigureAwait(false);
            Check.Equal(0, over.Runner.Calls.Count, "超限不得启动进程");
        }

        // 总量上限（256 MiB）：9 × 30 MiB 的声明在读取任何文件之前被拒绝。
        using (var total = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]))
        {
            var many = Enumerable.Range(1, 9)
                .Select(index => total.Segments[0] with
                {
                    SegmentId = $"seg-{index}",
                    Order = index,
                    WavPath = Path.Combine(Path.GetDirectoryName(total.Segments[0].WavPath)!, $"never-read-{index}.wav"),
                    Bytes = 30L * 1024 * 1024,
                    StartMs = (index - 1) * 600L,
                    EndMs = index * 600L,
                    SampleFrames = 1000,
                    SampleRate = 48000,
                })
                .ToList();
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(total.Runner)
                    .ComposeAsync(total.Request(segments: many), CancellationToken.None),
                MasterVideoComposerException.NarrationInvalid,
                "超过总量上限必须拒绝").ConfigureAwait(false);
            Check.Equal(0, total.Runner.Calls.Count, "总量超限不得启动进程");
        }

        // 声明合法、磁盘文件实际被撑大：长度不一致 → 拒绝，且不整体读入内存。
        using (var grown = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]))
        {
            using (var stream = new FileStream(grown.Segments[0].WavPath, FileMode.Open, FileAccess.Write))
            {
                stream.SetLength(FixedFfmpegMasterVideoComposer.MaximumWavBytes + 1024);
            }
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(grown.Runner).ComposeAsync(grown.Request(), CancellationToken.None),
                MasterVideoComposerException.NarrationInvalid,
                "被撑大的 WAV 必须拒绝").ConfigureAwait(false);
            Check.Equal(0, grown.Runner.Calls.Count, "撑大后不得启动进程");
        }

        // 畸形 WAV 头部：声明事实与文件内容（含 sha/长度）一致，只有头部本身异常 → 封闭码拒绝。
        var good = TestMedia.Wav(48000, 1, 48000, 440);
        var mutations = new (string Name, Func<byte[], byte[]> Mutate)[]
        {
            ("riff-size", wav => Patch(wav, 4, BitConverter.GetBytes((uint)wav.Length + 4))),
            ("block-align", wav => Patch(wav, 32, [4, 0])),
            ("byte-rate", wav => Patch(wav, 28, BitConverter.GetBytes(1u))),
            ("extensible", wav => Patch(wav, 20, [0xFE, 0xFF])),
            ("eight-bit", wav => Patch(wav, 34, [8, 0])),
            ("three-channels", wav => Patch(wav, 22, [3, 0])),
            ("rate-96k", wav => Patch(Patch(wav, 24, BitConverter.GetBytes(96000u)), 28, BitConverter.GetBytes(192000u))),
            ("not-riff", wav => Patch(wav, 0, [(byte)'X'])),
            ("odd-data", wav => Patch(wav, 40, BitConverter.GetBytes((uint)(wav.Length - 44 - 1)))),
            ("zero-data", wav => FixRiff([.. wav[..40], 0, 0, 0, 0])),
            ("truncated", wav => wav[..^10]),
            ("duplicate-data", wav => FixRiff([.. wav, .. "data"u8.ToArray(), 2, 0, 0, 0, 1, 1])),
            ("duplicate-fmt", wav => FixRiff([.. wav, .. "fmt "u8.ToArray(), 16, 0, 0, 0, .. wav[20..36]])),
            ("chunk-flood", wav => FixRiff([.. wav, .. Enumerable.Range(0, 70).SelectMany(
                _ => "JUNK"u8.ToArray().Concat(new byte[] { 0, 0, 0, 0 }))])),
        };
        foreach (var (name, mutate) in mutations)
        {
            using var env = Env.Create([new SegSpec(1, 48000, 1, 48000, 0, 2000)]);
            var bytes = mutate(good);
            var path = env.Segments[0].WavPath;
            await File.WriteAllBytesAsync(path, bytes).ConfigureAwait(false);
            var segment = env.Segments[0] with { Bytes = bytes.LongLength, Sha256 = TestMedia.Sha(bytes) };
            await Check.ThrowsAsync(
                () => new FixedFfmpegMasterVideoComposer(env.Runner)
                    .ComposeAsync(env.Request(segments: [segment]), CancellationToken.None),
                MasterVideoComposerException.NarrationInvalid,
                $"畸形 WAV（{name}）必须以封闭码拒绝").ConfigureAwait(false);
            Check.Equal(0, env.Runner.Calls.Count, $"畸形 WAV（{name}）不得启动进程");
            Check.True(!File.Exists(env.OutputPath), $"畸形 WAV（{name}）不得写输出");
        }

        // 回归：精确填满窗口的合法 WAV 仍被接受。
        using var exact = Env.Create([new SegSpec(1, 48000, 1, 48000, 0, 1000)]);
        await new FixedFfmpegMasterVideoComposer(exact.Runner).ComposeAsync(exact.Request(), CancellationToken.None)
            .ConfigureAwait(false);
        Check.True(File.Exists(exact.OutputPath), "精确窗口 WAV 仍被接受");
    }

    private static byte[] Patch(byte[] source, int offset, byte[] value)
    {
        var copy = (byte[])source.Clone();
        value.CopyTo(copy, offset);
        return copy;
    }

    private static byte[] FixRiff(byte[] wav) => Patch(wav, 4, BitConverter.GetBytes((uint)wav.Length - 8));

    // ── TOCTOU：校验后的输入在 ffprobe/ffmpeg 全程持有只读共享句柄 ───────────────────────────────
    private static async Task HeldHandlesBlockReplacementAsync()
    {
        using var env = Env.Create(
            [new SegSpec(1, 24000, 1, 24000, 0, 2500), new SegSpec(2, 44100, 2, 44100, 2500, 5000)]);
        var targets = new[] { env.Visual.Path }.Concat(env.Segments.Select(segment => segment.WavPath)).ToArray();
        var decoys = targets.ToDictionary(path => path, path => File.WriteAllBytesAsync(path + ".decoy", [7, 7, 7]));
        await Task.WhenAll(decoys.Values).ConfigureAwait(false);
        var before = targets.ToDictionary(path => path, path => TestMedia.Sha(File.ReadAllBytes(path)));
        var unexpected = new List<string>();
        var observed = 0;
        env.Runner.OnProcess = _ =>
        {
            observed++;
            foreach (var path in targets)
            {
                unexpected.AddRange(HostileReplacementAttempts(path, path + ".decoy").Select(name => $"{Path.GetFileName(path)}:{name}"));
                // 读取仍然允许（ffprobe/ffmpeg 需要读取）。
                Check.True(File.ReadAllBytes(path).Length > 0, "持有句柄时仍必须允许读取");
            }
        };
        await new FixedFfmpegMasterVideoComposer(env.Runner).ComposeAsync(env.Request(), CancellationToken.None)
            .ConfigureAwait(false);
        Check.Equal(3, observed, "输入 ffprobe、ffmpeg、输出 ffprobe 三次进程调用都应在持有句柄时发生");
        Check.Equal(0, unexpected.Count, "持有句柄期间任何替换/写入/删除/重命名都必须被拒绝：" + string.Join(",", unexpected));
        foreach (var path in targets)
        {
            Check.Equal(before[path], TestMedia.Sha(File.ReadAllBytes(path)), "输入字节保持不变");
        }
        AssertReleased(targets, "成功后");

        // 失败路径同样释放句柄。
        using var failing = Env.Create([new SegSpec(1, 24000, 1, 24000, 0, 2000)]);
        failing.Runner.Mode = FakeMode.ExitFailure;
        await Check.ThrowsAsync(
            () => new FixedFfmpegMasterVideoComposer(failing.Runner).ComposeAsync(failing.Request(), CancellationToken.None),
            MasterVideoComposerException.FfmpegFailed,
            "ffmpeg 失败").ConfigureAwait(false);
        AssertReleased([failing.Visual.Path, failing.Segments[0].WavPath], "失败后");
        Check.True(!File.Exists(failing.OutputPath), "失败后不得留下输出");
    }

    private static List<string> HostileReplacementAttempts(string path, string decoy)
    {
        var succeeded = new List<string>();
        void Try(string name, Action action)
        {
            try
            {
                action();
                succeeded.Add(name);
            }
            catch (IOException)
            {
                // 共享冲突：预期。
            }
            catch (UnauthorizedAccessException)
            {
                // 预期。
            }
        }
        Try("write", () => File.WriteAllBytes(path, [9, 9, 9]));
        Try("append", () => File.AppendAllText(path, "x"));
        Try("delete", () => File.Delete(path));
        Try("rename-away", () => File.Move(path, path + ".moved"));
        Try("replace-over", () => File.Move(decoy, path, overwrite: true));
        Try("open-write", () =>
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Write, FileShare.ReadWrite);
        });
        return succeeded;
    }

    private static void AssertReleased(IEnumerable<string> paths, string scenario)
    {
        foreach (var path in paths)
        {
            var moved = path + ".released";
            File.Move(path, moved);
            File.Move(moved, path);
        }
        Check.True(true, scenario + "句柄已释放");
    }
}
