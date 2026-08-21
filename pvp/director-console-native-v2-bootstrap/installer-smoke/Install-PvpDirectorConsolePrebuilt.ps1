# PVP Director Console Native v2 - PREBUILT installer. No source build on user PC.
[CmdletBinding()]
param([string]$PackageRoot = $PSScriptRoot)

$ProductRoot    = Join-Path $env:LOCALAPPDATA 'PVP\DirectorConsole'
$VersionsRoot   = Join-Path $ProductRoot 'versions'
$ReportsRoot    = Join-Path $ProductRoot 'reports'
$BackupsRoot    = Join-Path $ProductRoot 'backups'
$CurrentPath    = Join-Path $ProductRoot 'current_version.json'
$PreviousPath   = Join-Path $ProductRoot 'previous_version.json'
$ManifestPath   = Join-Path $PackageRoot 'release-manifest.json'
$PayloadRoot    = Join-Path $PackageRoot 'payload'
$ExtensionRoot  = 'C:\AI\PVP\producer\extensions\director_console_native_v2'
$ExtensionsRoot = 'C:\AI\PVP\producer\extensions'
$ProjectDir     = 'C:\AI\PVP\projects\PVP_First_Real_Director_Project_malamute_office_001'
$Timestamp      = Get-Date -Format 'yyyyMMdd-HHmmss'
$ReportDir      = Join-Path $ReportsRoot "install-$Timestamp"
$ReportPath     = Join-Path $ReportDir 'INSTALL_REPORT.json'
$LogPath        = Join-Path $ReportDir 'INSTALL.log'
$ResultZip      = Join-Path $PackageRoot "PVP_DIRECTOR_CONSOLE_N6E22_INSTALL_RESULT_$Timestamp.zip"
$Mutex          = $null
$MutexOwned     = $false
$ExtensionBackup = $null
$PreviousCurrent = $null
$PreviousPrevious = $null
$ExtensionChanged = $false
$ShortcutsChanged = $false

$BootstrapLog = Join-Path $PackageRoot 'PVP_DIRECTOR_CONSOLE_N6E22_BOOTSTRAP.log'
$BootstrapSmoke = ([string]$env:PVP_INSTALLER_BOOTSTRAP_SMOKE -eq '1')

function Write-BootstrapLog([string]$Message) {
    try {
        [System.IO.File]::AppendAllText($BootstrapLog, ((Get-Date).ToUniversalTime().ToString('o')+"`t"+$Message+[Environment]::NewLine), (New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false))
    } catch { }
}

function Write-Utf8NoBom([string]$Path,[string]$Value) {
    [System.IO.File]::WriteAllText($Path,$Value,(New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false))
}
function Write-JsonAtomic($Value,[string]$Path) {
    $tmp="$Path.tmp"
    Write-Utf8NoBom $tmp ($Value | ConvertTo-Json -Depth 30)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}
function Log([string]$Level,[string]$Message) {
    $line="{0}`t{1}`t{2}" -f (Get-Date).ToUniversalTime().ToString('o'),$Level,$Message
    [System.IO.File]::AppendAllText($LogPath,$line+[Environment]::NewLine,(New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false))
}
function Progress([int]$Percent,[string]$Stage,[string]$Detail) {
    Write-Progress -Activity 'PVP Director Console Setup' -Status "$Stage - $Detail" -PercentComplete $Percent
    Write-Host ("[{0,3}%] {1} - {2}" -f $Percent,$Stage,$Detail)
    Log 'INFO' "$Percent% | $Stage | $Detail"
}
function Assert-SafeRelativePath([string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative.Contains('..') -or [System.IO.Path]::IsPathRooted($Relative)) {
        throw "Unsafe manifest path: $Relative"
    }
}
function Assert-PayloadManifest($Manifest,[string]$Root) {
    foreach($entry in $Manifest.files) {
        $relative=[string]$entry.path; Assert-SafeRelativePath $relative
        $path=Join-Path $Root ($relative -replace '/','\')
        if(-not (Test-Path -LiteralPath $path)){ throw "Payload file missing: $relative" }
        $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if($hash -ne [string]$entry.sha256){ throw "Payload SHA mismatch: $relative" }
        if((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes){ throw "Payload size mismatch: $relative" }
    }
}
function Invoke-Native([string]$FilePath,[string[]]$Arguments,[int]$TimeoutSeconds=90) {
    $quote = { param([string]$v) if($v -notmatch '[\s"]'){ $v } else { '"'+($v -replace '"','\\"')+'"' } }
    $argLine=($Arguments | ForEach-Object { & $quote $_ }) -join ' '
    $si=New-Object System.Diagnostics.ProcessStartInfo
    $si.FileName=$FilePath; $si.Arguments=$argLine; $si.UseShellExecute=$false; $si.CreateNoWindow=$true
    $si.RedirectStandardOutput=$true; $si.RedirectStandardError=$true
    $p=New-Object System.Diagnostics.Process; $p.StartInfo=$si
    try {
        if(-not $p.Start()){ throw "Unable to start: $FilePath" }
        $outTask=$p.StandardOutput.ReadToEndAsync(); $errTask=$p.StandardError.ReadToEndAsync()
        if(-not $p.WaitForExit($TimeoutSeconds*1000)){
            try{$p.Kill()}catch{}; try{$p.WaitForExit()}catch{}; throw "Native command timeout: $FilePath"
        }
        $p.WaitForExit(); $p.Refresh()
        $stdout=$outTask.GetAwaiter().GetResult(); $stderr=$errTask.GetAwaiter().GetResult(); $code=[int]$p.ExitCode
        if($code -ne 0){ throw "Native command failed ($code): $FilePath`n$stderr`n$stdout" }
        return [pscustomobject]@{ ExitCode=$code; StdOut=$stdout; StdErr=$stderr }
    } finally { $p.Dispose() }
}
function Get-Python {
    $p=Join-Path $env:USERPROFILE '.conda\envs\pvp\python.exe'
    if(Test-Path -LiteralPath $p){ return $p }
    $cmd=Get-Command python.exe -ErrorAction SilentlyContinue
    if($null -ne $cmd){ return $cmd.Source }
    throw 'PVP Python runtime not found. No runtime will be installed automatically.'
}
function Get-ShortcutPaths {
    @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'PVP Director Console.lnk'),
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PVP Director Console.lnk')
    )
}
function Set-Shortcuts([string]$Executable) {
    $shell=New-Object -ComObject WScript.Shell
    foreach($path in Get-ShortcutPaths){
        $dir=Split-Path -Parent $path; New-Item -ItemType Directory -Path $dir -Force | Out-Null
        $s=$shell.CreateShortcut($path); $s.TargetPath=$Executable; $s.WorkingDirectory=Split-Path -Parent $Executable
        $s.Description='PVP Director Console'; $s.Save()
    }
}
function Remove-Shortcuts { foreach($p in Get-ShortcutPaths){ Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } }
function Probe-ComfyUI {
    $obj=[ordered]@{ endpoint='http://127.0.0.1:8188'; status='UNKNOWN'; system_stats=$null; object_info_class_count=$null; error=$null }
    try {
        $stats=Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -Method Get -TimeoutSec 3
        $info=Invoke-RestMethod -Uri 'http://127.0.0.1:8188/object_info' -Method Get -TimeoutSec 5
        $obj.status='ONLINE'; $obj.system_stats=$stats; $obj.object_info_class_count=@($info.PSObject.Properties).Count
    } catch { $obj.status='UNKNOWN'; $obj.error=$_.Exception.Message }
    $obj
}
function Stop-ExistingDirectorRuntime {
    Get-Process -Name 'PVP Director Console' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    try {
        $listeners=@(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop)
        foreach($listener in $listeners){
            $pid=[int]$listener.OwningProcess
            $wmi=Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $pid) -ErrorAction SilentlyContinue
            if($null -ne $wmi -and ([string]$wmi.Name) -match '^python(w)?\\.exe$' -and ([string]$wmi.CommandLine) -like '*pvp_director_native_v2.service_cli*'){
                Stop-Process -Id $pid -Force -ErrorAction Stop
                Log 'INFO' ("Stopped orphan Director Core PID="+$pid)
            }
        }
    } catch { Log 'INFO' ("Runtime cleanup skipped: "+$_.Exception.Message) }
}
function Restore-OnFailure {
    try {
        Get-Process -Name 'PVP Director Console' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        if($ExtensionChanged){
            if(Test-Path -LiteralPath $ExtensionRoot){ Remove-Item -LiteralPath $ExtensionRoot -Recurse -Force }
            if($null -ne $ExtensionBackup -and (Test-Path -LiteralPath $ExtensionBackup)){
                Copy-Item -LiteralPath $ExtensionBackup -Destination $ExtensionRoot -Recurse -Force
            }
        }
        if($null -ne $PreviousCurrent){
            Write-JsonAtomic $PreviousCurrent $CurrentPath
            Set-Shortcuts ([string]$PreviousCurrent.executable)
        } else { Remove-Item -LiteralPath $CurrentPath -Force -ErrorAction SilentlyContinue; Remove-Shortcuts }
        if($null -ne $PreviousPrevious){ Write-JsonAtomic $PreviousPrevious $PreviousPath }
    } catch { Log 'ERROR' ("Rollback error: "+$_.Exception.Message) }
}

$bootstrapReady=$false
try {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'Continue'
    try { [Console]::OutputEncoding = (New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false) } catch { Write-BootstrapLog ("Console output encoding skipped: "+$_.Exception.Message) }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Remove-Item -LiteralPath $BootstrapLog -Force -ErrorAction SilentlyContinue
    Write-BootstrapLog 'bootstrap-start'
    $Mutex = New-Object -TypeName System.Threading.Mutex -ArgumentList $false,'Global\PVP.DirectorConsole.NativeV2.Installer'
    New-Item -ItemType Directory -Path $VersionsRoot,$ReportsRoot,$BackupsRoot,$ReportDir -Force | Out-Null
    Write-BootstrapLog ("report-dir="+$ReportDir)
    $bootstrapReady=$true
} catch {
    Write-BootstrapLog ("BOOTSTRAP_FAIL: "+$_.Exception.ToString())
    Write-Host ("[BOOTSTRAP FAIL] "+$_.Exception.Message) -ForegroundColor Red
    Write-Host ("BOOTSTRAP_LOG="+$BootstrapLog)
    exit 91
}

if($BootstrapSmoke){
    try {
        $smoke=[ordered]@{schema_version='1.0';status='pass';stage='bootstrap-smoke';package_root=$PackageRoot;report_dir=$ReportDir;generated_at=(Get-Date).ToUniversalTime().ToString('o')}
        $smokePath=Join-Path $ReportDir 'BOOTSTRAP_SMOKE.json'
        [System.IO.File]::WriteAllText($smokePath,($smoke|ConvertTo-Json -Depth 5),(New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false))
        if(Test-Path -LiteralPath $ResultZip){Remove-Item -LiteralPath $ResultZip -Force}
        [System.IO.Compression.ZipFile]::CreateFromDirectory($ReportDir,$ResultZip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
        Write-BootstrapLog ("bootstrap-smoke-pass result="+$ResultZip)
        Write-Host ("RESULT_ZIP="+$ResultZip)
        if($null -ne $Mutex){$Mutex.Dispose()}
        exit 0
    } catch {
        Write-BootstrapLog ("BOOTSTRAP_SMOKE_FAIL: "+$_.Exception.ToString())
        Write-Host ("[BOOTSTRAP SMOKE FAIL] "+$_.Exception.Message) -ForegroundColor Red
        if($null -ne $Mutex){$Mutex.Dispose()}
        exit 92
    }
}

$report=[ordered]@{
    schema_version='2.0'; status='running'; generated_at=(Get-Date).ToUniversalTime().ToString('o');
    version=$null; source_build_on_user_pc=$false; sdk_install_on_user_pc=$false; model_download=$false; media_submission=$false;
    app_self_test=$null; backend_bootstrap=$null; comfyui=$null; install_path=$null; extension_path=$ExtensionRoot; error=$null
}
$exitCode=1
try {
    try{$MutexOwned=$Mutex.WaitOne(0)}catch[System.Threading.AbandonedMutexException]{$MutexOwned=$true}
    if(-not $MutexOwned){ throw 'Another PVP Director Console install/rollback is already running.' }
    Progress 5 'PACKAGE' 'verify prebuilt manifest'
    if(-not (Test-Path -LiteralPath $ManifestPath)){ throw 'release-manifest.json missing.' }
    if(-not (Test-Path -LiteralPath $PayloadRoot)){ throw 'payload directory missing.' }
    $manifest=Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if([string]$manifest.release_type -ne 'prebuilt'){ throw 'Package is not prebuilt.' }
    if([string]$manifest.target -ne 'win-x64'){ throw 'Package target is not win-x64.' }
    if([bool]$manifest.source_build_on_user_pc){ throw 'Package incorrectly requests source build on user PC.' }
    Assert-PayloadManifest $manifest $PayloadRoot
    $version=[string]$manifest.version; $report.version=$version
    $finalPath=Join-Path $VersionsRoot $version; $report.install_path=$finalPath
    $staging=Join-Path $VersionsRoot ('.staging-'+$version+'-'+$PID)
    $python=Get-Python
    if(-not (Test-Path -LiteralPath 'C:\AI\PVP\producer')){ throw 'C:\AI\PVP\producer is missing.' }
    if(-not (Test-Path -LiteralPath $ProjectDir)){ throw "PVP project is missing: $ProjectDir" }
    New-Item -ItemType Directory -Path $ExtensionsRoot -Force | Out-Null
    if(Test-Path -LiteralPath $CurrentPath){ $PreviousCurrent=Get-Content -LiteralPath $CurrentPath -Raw | ConvertFrom-Json }
    if(Test-Path -LiteralPath $PreviousPath){ $PreviousPrevious=Get-Content -LiteralPath $PreviousPath -Raw | ConvertFrom-Json }

    Progress 20 'APP' 'install CI-prebuilt native executable'
    if(Test-Path -LiteralPath $staging){ Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Copy-Item -Path (Join-Path $PayloadRoot 'app\*') -Destination $staging -Recurse -Force
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $staging 'release-manifest.json') -Force
    $appEntry=$manifest.files | Where-Object { [string]$_.path -eq 'app/PVP Director Console.exe' } | Select-Object -First 1
    $stagedExe=Join-Path $staging 'PVP Director Console.exe'
    if($null -eq $appEntry -or -not (Test-Path -LiteralPath $stagedExe)){ throw 'Prebuilt executable missing.' }
    if((Get-FileHash -LiteralPath $stagedExe -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$appEntry.sha256){ throw 'Prebuilt executable SHA mismatch after staging.' }
    if(Test-Path -LiteralPath $finalPath){ Remove-Item -LiteralPath $finalPath -Recurse -Force }
    Move-Item -LiteralPath $staging -Destination $finalPath
    $exe=Join-Path $finalPath 'PVP Director Console.exe'

    Progress 32 'RUNTIME' 'stop previous Director Console runtime'
    Stop-ExistingDirectorRuntime

    Progress 40 'CORE' 'backup and install Director Core extension'
    if(Test-Path -LiteralPath $ExtensionRoot){
        $ExtensionBackup=Join-Path $BackupsRoot ("director_console_native_v2-$Timestamp")
        Copy-Item -LiteralPath $ExtensionRoot -Destination $ExtensionBackup -Recurse -Force
    }
    $extStaging=Join-Path $ExtensionsRoot ('.director_console_native_v2.staging-'+$PID)
    if(Test-Path -LiteralPath $extStaging){ Remove-Item -LiteralPath $extStaging -Recurse -Force }
    New-Item -ItemType Directory -Path $extStaging -Force | Out-Null
    Copy-Item -Path (Join-Path $PayloadRoot 'extension\*') -Destination $extStaging -Recurse -Force
    foreach($entry in ($manifest.files | Where-Object { ([string]$_.path).StartsWith('extension/') })){
        $relative=([string]$entry.path).Substring('extension/'.Length)
        $path=Join-Path $extStaging ($relative -replace '/','\')
        if(-not (Test-Path -LiteralPath $path)){ throw "Extension file missing after staging: $relative" }
        if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.sha256){ throw "Extension SHA mismatch: $relative" }
    }
    if(Test-Path -LiteralPath $ExtensionRoot){ Remove-Item -LiteralPath $ExtensionRoot -Recurse -Force }
    Move-Item -LiteralPath $extStaging -Destination $ExtensionRoot
    $ExtensionChanged=$true

    Progress 58 'SELFTEST' 'run published native headless self-test'
    $nativeSelf=Join-Path $ReportDir 'NATIVE_SELF_TEST.json'
    Invoke-Native $exe @('--self-test','--self-test-output',$nativeSelf) 60 | Out-Null
    $nativeResult=Get-Content -LiteralPath $nativeSelf -Raw | ConvertFrom-Json
    if([string]$nativeResult.status -ne 'pass'){ throw 'Native self-test did not pass.' }
    $report.app_self_test=$nativeResult

    Progress 70 'CORE' 'bootstrap SQLite overlay without changing Canonical facts'
    $env:PYTHONPATH=Join-Path $ExtensionRoot 'src'
    $boot=Invoke-Native $python @('-m','pvp_director_native_v2.bootstrap_cli','--project-dir',$ProjectDir) 60
    Write-Utf8NoBom (Join-Path $ReportDir 'BACKEND_BOOTSTRAP.json') $boot.StdOut
    $bootResult=$boot.StdOut | ConvertFrom-Json
    if([string]$bootResult.status -ne 'READY' -or -not [bool]$bootResult.canonical_fingerprint_unchanged){ throw 'Director Core bootstrap failed safety gate.' }
    $report.backend_bootstrap=$bootResult

    Progress 80 'COMFYUI' 'read local capability only; offline does not fail install'
    $comfy=Probe-ComfyUI; $report.comfyui=$comfy
    Write-JsonAtomic $comfy (Join-Path $ReportDir 'COMFYUI_PROBE.json')

    Progress 88 'ACTIVATE' 'write version pointer and shortcuts'
    if($null -ne $PreviousCurrent){ Write-JsonAtomic $PreviousCurrent $PreviousPath }
    $current=[ordered]@{ version=$version; executable=$exe; path=$finalPath; extension=$ExtensionRoot; extension_backup=$ExtensionBackup; activated_at=(Get-Date).ToUniversalTime().ToString('o'); native_exe_sha256=[string]$appEntry.sha256 }
    Write-JsonAtomic $current $CurrentPath
    Set-Shortcuts $exe; $ShortcutsChanged=$true

    Progress 94 'LAUNCH' 'start PVP Director Console'
    Get-Process -Name 'PVP Director Console' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $proc=Start-Process -FilePath $exe -WorkingDirectory $finalPath -PassThru
    Start-Sleep -Seconds 3; $proc.Refresh()
    if($proc.HasExited){ throw "PVP Director Console exited immediately with code $($proc.ExitCode)." }

    $report.status='pass'; Write-JsonAtomic $report $ReportPath
    Progress 100 'DONE' 'prebuilt PVP Director Console installed and started'
    $exitCode=0
} catch {
    $report.status='fail'; $report.error=$_.Exception.Message; Log 'ERROR' $report.error
    Restore-OnFailure
    Write-JsonAtomic $report $ReportPath
    Write-Host ("[FAIL] "+$report.error) -ForegroundColor Red
} finally {
    Write-Progress -Activity 'PVP Director Console Setup' -Completed
    try {
        if(Test-Path -LiteralPath $ResultZip){ Remove-Item -LiteralPath $ResultZip -Force }
        [System.IO.Compression.ZipFile]::CreateFromDirectory($ReportDir,$ResultZip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
        Write-Host "RESULT_ZIP=$ResultZip"
    } catch { Write-Host ("RESULT_ZIP_ERROR="+$_.Exception.Message) }
    if($null -ne $Mutex){ if($MutexOwned){ $Mutex.ReleaseMutex() }; $Mutex.Dispose() }
}
exit $exitCode
