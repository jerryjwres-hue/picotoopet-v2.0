Option Explicit
Dim shell, fso, scriptDir, psScript, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript = fso.BuildPath(scriptDir, "Install-Phase2Prebuilt.ps1")
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & psScript & """ -PackageRoot """ & scriptDir & """"
exitCode = shell.Run(command, 1, True)
WScript.Quit exitCode
