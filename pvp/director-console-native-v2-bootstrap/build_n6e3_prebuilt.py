from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

VERIFY_PS1 = r'''# PVP Director Console Native v2 - verify installed prebuilt version.
[CmdletBinding()] param()
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$root=Join-Path $env:LOCALAPPDATA 'PVP\DirectorConsole'
$currentPath=Join-Path $root 'current_version.json'
if(-not (Test-Path -LiteralPath $currentPath)){ throw 'No installed PVP Director Console version pointer.' }
$current=Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
$exe=[string]$current.executable
if(-not (Test-Path -LiteralPath $exe)){ throw "Executable missing: $exe" }
$manifestPath=Join-Path ([string]$current.path) 'release-manifest.json'
if(-not (Test-Path -LiteralPath $manifestPath)){ throw 'Installed release manifest missing.' }
$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$appEntry=$manifest.files | Where-Object { [string]$_.path -eq 'app/PVP Director Console.exe' } | Select-Object -First 1
if($null -eq $appEntry){ throw 'Manifest app entry missing.' }
$actual=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if($actual -ne [string]$appEntry.sha256){ throw 'Installed executable SHA mismatch.' }
$ext='C:\AI\PVP\producer\extensions\director_console_native_v2'
foreach($entry in ($manifest.files | Where-Object { ([string]$_.path).StartsWith('extension/') })){
    $rel=([string]$entry.path).Substring('extension/'.Length); $p=Join-Path $ext ($rel -replace '/','\')
    if(-not (Test-Path -LiteralPath $p)){ throw "Installed extension file missing: $rel" }
    if((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.sha256){ throw "Installed extension SHA mismatch: $rel" }
}
Write-Host 'PVP_DIRECTOR_CONSOLE_VERIFY=PASS'
Write-Host ("VERSION="+[string]$current.version)
Write-Host ("EXE_SHA256="+$actual)
'''

ROLLBACK_PS1 = r'''# PVP Director Console Native v2 - rollback one installed prebuilt version.
[CmdletBinding()] param()
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'PVP\DirectorConsole'
$currentPath=Join-Path $root 'current_version.json'; $previousPath=Join-Path $root 'previous_version.json'
if(-not (Test-Path -LiteralPath $previousPath)){ throw 'No previous PVP Director Console version is available.' }
$current=if(Test-Path -LiteralPath $currentPath){Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json}else{$null}
$previous=Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
Get-Process -Name 'PVP Director Console' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$ext='C:\AI\PVP\producer\extensions\director_console_native_v2'
if($null -ne $current -and $null -ne $current.extension_backup -and (Test-Path -LiteralPath ([string]$current.extension_backup))){
    if(Test-Path -LiteralPath $ext){Remove-Item -LiteralPath $ext -Recurse -Force}
    Copy-Item -LiteralPath ([string]$current.extension_backup) -Destination $ext -Recurse -Force
}
[System.IO.File]::WriteAllText($currentPath,($previous|ConvertTo-Json -Depth 20),(New-Object System.Text.UTF8Encoding($false)))
Remove-Item -LiteralPath $previousPath -Force
$shell=New-Object -ComObject WScript.Shell
foreach($p in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'PVP Director Console.lnk'),(Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PVP Director Console.lnk'))){
    $s=$shell.CreateShortcut($p); $s.TargetPath=[string]$previous.executable; $s.WorkingDirectory=Split-Path -Parent ([string]$previous.executable); $s.Description='PVP Director Console'; $s.Save()
}
Start-Process -FilePath ([string]$previous.executable) -WorkingDirectory ([string]$previous.path)
Write-Host 'PVP_DIRECTOR_CONSOLE_ROLLBACK=PASS'
'''

VERIFY_VBS = '''Option Explicit\r\nDim shell, fso, scriptDir, psScript, command, exitCode\r\nSet shell = CreateObject("WScript.Shell")\r\nSet fso = CreateObject("Scripting.FileSystemObject")\r\nscriptDir = fso.GetParentFolderName(WScript.ScriptFullName)\r\npsScript = fso.BuildPath(scriptDir, "Verify-PvpDirectorConsolePrebuilt.ps1")\r\ncommand = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & psScript & Chr(34)\r\nexitCode = shell.Run(command, 1, True)\r\nWScript.Quit exitCode\r\n'''

ROLLBACK_VBS = '''Option Explicit\r\nDim shell, fso, scriptDir, psScript, command, exitCode\r\nSet shell = CreateObject("WScript.Shell")\r\nSet fso = CreateObject("Scripting.FileSystemObject")\r\nscriptDir = fso.GetParentFolderName(WScript.ScriptFullName)\r\npsScript = fso.BuildPath(scriptDir, "Rollback-PvpDirectorConsolePrebuilt.ps1")\r\ncommand = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & psScript & Chr(34)\r\nexitCode = shell.Run(command, 1, True)\r\nWScript.Quit exitCode\r\n'''


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def copy_runtime_extension(src: Path, dst: Path) -> None:
    for path in src.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if 'tests' in rel.parts or '__pycache__' in rel.parts or path.suffix == '.pyc':
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--native-publish', required=True)
    parser.add_argument('--installer-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--head-sha', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()

    source = Path(args.source_root).resolve()
    native = Path(args.native_publish).resolve()
    installer = Path(args.installer_root).resolve()
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    short = args.head_sha[:7]
    version = f'2.0.0-n6e3-prebuilt-{short}'
    package = output_root / 'PVP_DirectorConsole_Native_V2_N6E3_PREBUILT'
    if package.exists():
        shutil.rmtree(package)
    (package / 'payload/app').mkdir(parents=True)

    extension_source = source / 'payload/producer/extensions/director_console_native_v2'
    extension_target = package / 'payload/extension'
    exe_source = native / 'PVP Director Console.exe'
    if not exe_source.is_file():
        raise SystemExit(f'missing published exe: {exe_source}')
    if not extension_source.is_dir():
        raise SystemExit(f'missing extension source: {extension_source}')
    shutil.copy2(exe_source, package / 'payload/app/PVP Director Console.exe')
    copy_runtime_extension(extension_source, extension_target)

    install_ps = (installer / 'Install-PvpDirectorConsolePrebuilt.N6E22.ps1').read_text(encoding='utf-8-sig')
    install_ps = install_ps.replace('N6E22', 'N6E3').replace('N6E2.2', 'N6E3')
    (package / 'Install-PvpDirectorConsolePrebuilt.N6E3.ps1').write_text(install_ps, encoding='utf-8', newline='\r\n')
    cmd = (installer / 'INSTALL_PVP_DIRECTOR_CONSOLE.cmd').read_text(encoding='utf-8-sig')
    cmd = cmd.replace('N6E22', 'N6E3').replace('N6E2.2', 'N6E3')
    (package / 'INSTALL_PVP_DIRECTOR_CONSOLE.cmd').write_text(cmd, encoding='ascii', newline='\r\n')
    shutil.copy2(installer / 'INSTALL_PVP_DIRECTOR_CONSOLE.vbs', package / 'INSTALL_PVP_DIRECTOR_CONSOLE.vbs')
    (package / 'Verify-PvpDirectorConsolePrebuilt.ps1').write_text(VERIFY_PS1, encoding='utf-8', newline='\r\n')
    (package / 'Rollback-PvpDirectorConsolePrebuilt.ps1').write_text(ROLLBACK_PS1, encoding='utf-8', newline='\r\n')
    (package / 'VERIFY_PVP_DIRECTOR_CONSOLE.vbs').write_text(VERIFY_VBS, encoding='ascii', newline='')
    (package / 'ROLLBACK_PVP_DIRECTOR_CONSOLE.vbs').write_text(ROLLBACK_VBS, encoding='ascii', newline='')

    files = []
    for path in sorted((package / 'payload').rglob('*')):
        if path.is_file():
            rel = path.relative_to(package / 'payload').as_posix()
            files.append({'path': rel, 'sha256': sha256(path), 'size_bytes': path.stat().st_size})

    manifest = {
        'schema_version': '2.0',
        'release_type': 'prebuilt',
        'version': version,
        'product': 'PVP Director Console',
        'freeze_id': 'PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1',
        'target': 'win-x64',
        'source_checkpoint': 'N6E3',
        'native_build_head': args.head_sha,
        'native_ci_run_id': int(args.run_id),
        'source_build_on_user_pc': False,
        'sdk_install_on_user_pc': False,
        'model_download_on_install': False,
        'media_submission_on_install': False,
        'files': files,
        'launcher_hotfix': 'N6E3-CONVERGED',
        'installer_bootstrap_gate': 'pending-final-ci',
    }
    (package / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    readme = f'''PVP Director Console Native v2 - N6E3 预编译安装包\n\n安装：双击 INSTALL_PVP_DIRECTOR_CONSOLE.cmd\n\n版本：{version}\n冻结架构：PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1\nGitHub Windows CI run：{args.run_id}\nGitHub head：{args.head_sha}\n\n本包不会在用户电脑上编译源码、安装 .NET SDK、安装 pip/conda 依赖、下载模型或提交 ComfyUI 生成任务。\n安装器会验证 payload SHA-256、运行 Native self-test、启动 Director Core SQLite overlay，并在成功后启动导演台。\n失败时会自动回滚，并生成 PVP_DIRECTOR_CONSOLE_N6E3_INSTALL_RESULT_*.zip。\n\n验证：VERIFY_PVP_DIRECTOR_CONSOLE.vbs\n回滚：ROLLBACK_PVP_DIRECTOR_CONSOLE.vbs\n'''
    (package / 'README_INSTALL_CN.txt').write_text(readme, encoding='utf-8-sig', newline='\r\n')

    evidence = package / 'evidence'
    evidence.mkdir()
    for name in ('native-self-test.json', 'native-exe.sha256'):
        src = native.parent / name
        if src.exists():
            shutil.copy2(src, evidence / name)
    (evidence / 'build-metadata.json').write_text(
        json.dumps({'head_sha': args.head_sha, 'run_id': int(args.run_id), 'version': version}, indent=2) + '\n',
        encoding='utf-8',
    )

    zip_path = output_root / f'PVP_DirectorConsole_Native_V2_N6E3_PREBUILT_{short}.zip'
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(package).as_posix())
    digest = sha256(zip_path)
    zip_path.with_suffix(zip_path.suffix + '.sha256').write_text(f'{digest}  {zip_path.name}\n', encoding='ascii')
    print(json.dumps({'status': 'pass', 'version': version, 'package_dir': str(package), 'zip': str(zip_path), 'sha256': digest, 'payload_files': len(files)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
