using PicotooPet.Desktop.Services;

// ── Native Windows fake-API tests: execute the real shared library in the approved WPF build. ──
if (!typeof(ProductionExecutionService).GetConstructors().Any(ctor =>
        ctor.GetParameters().Any(parameter =>
            parameter.ParameterType.Name == "IProductionExecutionGateway")))
{
    throw new InvalidOperationException("P0_SHARED_EXECUTOR_GATEWAY_MISSING");
}
await PicotooPet.MediaWorker.SmokeTests.RecoveryTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.RecoveryFixTests.RunAsync();
await PicotooPet.MediaWorker.SmokeTests.MultiShotProductionTests.RunAsync();
PicotooPet.MediaWorker.SmokeTests.ReferenceV11BindingTests.Run();
await PicotooPet.MediaWorker.SmokeTests.LegacyContractTests.RunAsync();
PicotooPet.MediaWorker.SmokeTests.SameExeHostTests.Run();
Console.WriteLine("P0_SAME_EXE_WORKER_JOURNAL_RECOVERY=PASS");
