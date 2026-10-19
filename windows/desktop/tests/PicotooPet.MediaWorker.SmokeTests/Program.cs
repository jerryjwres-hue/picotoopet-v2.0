using PicotooPet.Desktop.Services;

if (args is ["--child", var mode, var root])
{
    await PicotooPet.MediaWorker.SmokeTests.ProcessTests.ChildAsync(mode, root);
    return;
}

// P0-B RED：原 executor 只能由 WPF 会话构造，不能被独立用户进程组合。
if (!typeof(ProductionExecutionService).GetConstructors().Any(c =>
        c.GetParameters().Any(p => p.ParameterType.Name == "IProductionExecutionGateway")))
    throw new InvalidOperationException("P0-B missing headless gateway: production must not depend on WPF lifetime.");
Console.WriteLine("MEDIA_WORKER_HEADLESS_BOUNDARY=PASS");
await PicotooPet.MediaWorker.SmokeTests.RecoveryTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.HostTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.ProcessTests.RunAsync();
