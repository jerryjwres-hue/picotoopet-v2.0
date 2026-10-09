using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.CaptionOverlay.SmokeTests;

/// <summary>闭集字体策略：Han→中文、Latin→英文、固定顺序、缺字体/缺字形有界、无调用方字体输入。</summary>
internal static class FontPolicyTests
{
    private static readonly (uint, uint) Latin = (0x20, 0x7E);
    private static readonly (uint, uint) Han = (0x3000, 0x9FFF);
    private static readonly (uint, uint) FullWidth = (0xFF00, 0xFFEF);

    public static void Run()
    {
        SmokeAssert.True(WindowsTextOverlayFontPolicy.ContainsHan("快速 dry"), "含汉字");
        SmokeAssert.True(!WindowsTextOverlayFontPolicy.ContainsHan("Fresh & Fast"), "纯拉丁不含汉字");
        SmokeAssert.Equal(
            "msyh.ttc",
            WindowsTextOverlayFontPolicy.CandidatesFor("你好")[0].FileName,
            "Han 使用中文闭集，msyh 优先");
        SmokeAssert.Equal(
            "arial.ttf",
            WindowsTextOverlayFontPolicy.CandidatesFor("Hello")[0].FileName,
            "Latin 使用英文闭集，arial 优先");
        SmokeAssert.Equal(
            "msyh.ttc|Deng.ttf|simhei.ttf|simsun.ttc",
            string.Join('|', WindowsTextOverlayFontPolicy.ChineseCandidates.Select(item => item.FileName)),
            "中文候选顺序冻结");
        SmokeAssert.Equal(
            "arial.ttf|segoeui.ttf|msyh.ttc",
            string.Join('|', WindowsTextOverlayFontPolicy.EnglishCandidates.Select(item => item.FileName)),
            "英文候选顺序冻结");

        var root = Path.Combine(Path.GetTempPath(), "picotoo-font-smoke-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            // 缺字体：目录为空。
            ExpectCode(root, "Hello", TextOverlayException.FontUnavailable, "无字体必须有界失败");

            // 仅 Latin 字体：英文成功；汉字 → GLYPH_MISSING（字体存在但不覆盖）。
            WriteFont(root, "arial.ttf", Latin);
            var english = new WindowsTextOverlayFontPolicy(root).Resolve("Hello 123");
            SmokeAssert.Equal("arial.ttf", english.FileName, "英文选择 arial");
            SmokeAssert.Equal(64, english.IdentitySha256.Length, "字体身份是 SHA-256");
            ExpectCode(root, "字幕", TextOverlayException.GlyphMissing, "字体不覆盖汉字必须 GLYPH_MISSING");

            // Deng 覆盖汉字；msyh 缺席 → 取 Deng（固定顺序第二位）。
            WriteFont(root, "Deng.ttf", Latin, Han, FullWidth);
            SmokeAssert.Equal(
                "Deng.ttf",
                new WindowsTextOverlayFontPolicy(root).Resolve("字幕测试：皮卡").FileName,
                "msyh 缺席时按固定顺序取 Deng");

            // msyh 出现后优先于 Deng；同输入同身份（确定性）。
            WriteFont(root, "msyh.ttc", Latin, Han, FullWidth);
            var first = new WindowsTextOverlayFontPolicy(root).Resolve("字幕测试：皮卡");
            var second = new WindowsTextOverlayFontPolicy(root).Resolve("字幕测试：皮卡");
            SmokeAssert.Equal("msyh.ttc", first.FileName, "msyh 优先");
            SmokeAssert.Equal(first.IdentitySha256, second.IdentitySha256, "字体身份确定");

            // 重解析点字体被拒绝。
            var linkRoot = Path.Combine(root, "link-fonts");
            Directory.CreateDirectory(linkRoot);
            var target = Path.Combine(root, "arial.ttf");
            try
            {
                File.CreateSymbolicLink(Path.Combine(linkRoot, "arial.ttf"), target);
                ExpectCode(linkRoot, "Hello", TextOverlayException.FontUnavailable, "重解析点字体必须拒绝");
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                Console.WriteLine("CAPTION_OVERLAY_FONT_REPARSE=UNVERIFIED(symlink privilege unavailable)");
            }

            // 过大字体被拒绝（不读入内存）。
            var bigRoot = Path.Combine(root, "big");
            Directory.CreateDirectory(bigRoot);
            using (var big = new FileStream(Path.Combine(bigRoot, "arial.ttf"), FileMode.Create))
            {
                big.SetLength(WindowsTextOverlayFontPolicy.MaxFontBytes + 1);
            }
            ExpectCode(bigRoot, "Hello", TextOverlayException.FontUnavailable, "超大字体必须拒绝");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }

        // 调用方无法提供字体：策略与渲染器公开面里没有任何接受字体路径/名称的重载。
        var surface = typeof(WindowsCaptionOverlayService).GetMethods()
            .Where(method => method.DeclaringType == typeof(WindowsCaptionOverlayService))
            .SelectMany(method => method.GetParameters())
            .Select(parameter => parameter.Name ?? string.Empty);
        SmokeAssert.True(
            !surface.Any(name => name.Contains("font", StringComparison.OrdinalIgnoreCase)
                || name.Contains("filter", StringComparison.OrdinalIgnoreCase)),
            "服务公开方法不得有字体/滤镜参数");
    }

    private static void WriteFont(string root, string name, params (uint, uint)[] ranges) =>
        File.WriteAllBytes(Path.Combine(root, name), WindowsSfntCmap.BuildFormat12Fixture(ranges));

    private static void ExpectCode(string root, string text, string code, string message)
    {
        try
        {
            new WindowsTextOverlayFontPolicy(root).Resolve(text);
        }
        catch (TextOverlayException exception)
        {
            SmokeAssert.Equal(code, exception.Code, message);
            return;
        }
        throw new InvalidOperationException($"{message}（未抛出）");
    }
}
