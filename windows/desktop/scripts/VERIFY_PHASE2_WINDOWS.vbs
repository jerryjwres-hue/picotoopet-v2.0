Option Explicit
Dim shell, fso, scriptPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "Verify-Phase2Windows.ps1")
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """"
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode
