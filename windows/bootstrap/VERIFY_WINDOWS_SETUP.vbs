Option Explicit
Dim shell, folder, command
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & folder & "\WindowsBootstrap.ps1"" -VerifyOnly"
shell.Run command, 0, True
