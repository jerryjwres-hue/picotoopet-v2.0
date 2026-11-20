Option Explicit
' Start only the bundled OpenSSH PowerShell bootstrap; never pass any API credentials.
Dim shell, fso, root, scriptPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(root, "Start-SecureMacTunnel.ps1")
If Not fso.FileExists(scriptPath) Then
    MsgBox "Missing secure tunnel script. Extract the complete trusted release ZIP.", vbCritical, "Picotoo Pet AI"
    WScript.Quit 2
End If
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """"
exitCode = shell.Run(command, 1, True)
WScript.Quit exitCode
