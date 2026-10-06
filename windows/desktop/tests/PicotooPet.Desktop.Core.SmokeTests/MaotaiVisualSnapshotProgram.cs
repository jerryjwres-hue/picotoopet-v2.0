namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>仅供 Windows 视觉证据 workflow 使用的独立 STA 入口。</summary>
internal static class MaotaiVisualSnapshotProgram
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Length < 1 || string.IsNullOrWhiteSpace(args[0]))
        {
            Console.Error.WriteLine("MAOTAI_VISUAL_SNAPSHOT=FAIL | missing output directory");
            return 2;
        }

        try
        {
            MaotaiVisualSnapshotSmokeTests.Run(args[0]);
            Console.WriteLine($"MAOTAI_VISUAL_SNAPSHOT=PASS | {Path.GetFullPath(args[0])}");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"MAOTAI_VISUAL_SNAPSHOT=FAIL | {exception}");
            return 2;
        }
    }
}
