using System.Runtime.CompilerServices;
using System.Threading;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>仅在显式视觉截图参数出现时短路普通 smoke 主流程；正常测试路径不受影响。</summary>
internal static class MaotaiVisualSnapshotModuleInitializer
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        var args = Environment.GetCommandLineArgs();
        var index = Array.FindIndex(
            args,
            value => string.Equals(
                value,
                "--maotai-visual-snapshot",
                StringComparison.Ordinal));
        if (index < 0)
        {
            return;
        }

        if (index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]))
        {
            Console.Error.WriteLine("MAOTAI_VISUAL_SNAPSHOT=FAIL | missing output directory");
            Environment.Exit(2);
            return;
        }

        Exception? failure = null;
        var outputDirectory = args[index + 1];
        var thread = new Thread(() =>
        {
            try
            {
                MaotaiVisualSnapshotSmokeTests.Run(outputDirectory);
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();

        if (!thread.Join(TimeSpan.FromSeconds(45)))
        {
            Console.Error.WriteLine("MAOTAI_VISUAL_SNAPSHOT=TIMEOUT | STA renderer exceeded 45 seconds");
            Environment.Exit(3);
            return;
        }

        if (failure is not null)
        {
            Console.Error.WriteLine($"MAOTAI_VISUAL_SNAPSHOT=FAIL | {failure}");
            Environment.Exit(2);
            return;
        }

        Console.WriteLine($"MAOTAI_VISUAL_SNAPSHOT=PASS | {Path.GetFullPath(outputDirectory)}");
        Environment.Exit(0);
    }
}
