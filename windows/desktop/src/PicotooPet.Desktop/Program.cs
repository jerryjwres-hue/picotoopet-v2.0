using PicotooPet.Desktop.Core.DevBroker;

namespace PicotooPet.Desktop;

/// <summary>在任何 WPF、XAML、单实例锁或桌面服务创建前分流固定子进程模式。</summary>
internal static class Program
{
    /// <summary>先处理无界面 Mock Broker；普通启动才创建 WPF Application。</summary>
    [STAThread]
    public static int Main(string[] args)
    {
        ArgumentNullException.ThrowIfNull(args);
        if (MockProviderChild.TryRun(
                args,
                Console.Out,
                Console.Error,
                out var brokerExitCode))
        {
            return brokerExitCode;
        }

        var application = new App();
        application.InitializeComponent();
        return application.Run();
    }
}
