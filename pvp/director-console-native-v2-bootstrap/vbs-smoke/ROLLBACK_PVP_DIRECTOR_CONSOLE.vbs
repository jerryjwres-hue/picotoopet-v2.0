Option Explicit
Dim shell, fso, scriptDir, psScript, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
psScript = fso.BuildPath(scriptDir, "Rollback-PvpDirectorConsolePrebuilt.ps1")
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & psScript & Chr(34)
exitCode = shell.Run(command, 1, True)
WScript.Quit exitCode
