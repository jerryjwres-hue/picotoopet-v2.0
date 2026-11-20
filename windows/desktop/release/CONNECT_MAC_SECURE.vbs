Option Explicit
' 只启动随安装包提供的受控 PowerShell SSH 客户端入口；无设备/Owner Token 参数。
Dim shell, fso, root, scriptPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(root, "Start-SecureMacTunnel.ps1")
If Not fso.FileExists(scriptPath) Then
    MsgBox "安装包缺少安全连接脚本，请重新获取完整安装包。", vbCritical, "Picotoo Pet AI"
    WScript.Quit 2
End If
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & scriptPath & """"
exitCode = shell.Run(command, 1, True)
WScript.Quit exitCode
