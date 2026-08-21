Option Explicit
Dim shell, fso, scriptDir, cmdPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
cmdPath = fso.BuildPath(scriptDir, "INSTALL_PVP_DIRECTOR_CONSOLE.cmd")
If Not fso.FileExists(cmdPath) Then
  MsgBox "Installer entry is missing: " & cmdPath, 16, "PVP Director Console Setup"
  WScript.Quit 2
End If
command = shell.ExpandEnvironmentStrings("%ComSpec%") & " /d /c " & Chr(34) & Chr(34) & cmdPath & Chr(34) & Chr(34)
exitCode = shell.Run(command, 1, True)
If exitCode <> 0 Then
  MsgBox "Installation failed with exit code " & CStr(exitCode) & "." & vbCrLf & "The command window contains the full error and will remain open until acknowledged.", 16, "PVP Director Console Setup"
End If
WScript.Quit exitCode
