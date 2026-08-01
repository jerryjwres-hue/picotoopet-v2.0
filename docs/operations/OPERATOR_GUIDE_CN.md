# 日常操作指南

安装完成后，普通任务不要求打开 Terminal、CMD 或 PowerShell。

- Mac Core 和健康监督由 launchd 自动启动。
- `gpt-oss:20b` 被卸载出内存时，健康监督器会重新执行常驻加载。
- 本地任务自动进入 SQLite 队列并恢复。
- 云端上传任务必须停在 `WaitingForApproval`，只有一次性批准令牌可恢复任务。
- Windows 模型检查或修复使用 VBS 双击入口。
- 原始 Maotai 数据、Raw Evidence 和原始媒体不被移动、覆盖或直接上传。

常用入口：

| 目的 | 入口 |
|---|---|
| Mac 安装/升级 | `scripts/mac/INSTALL_MAC.command` |
| Mac 验证 | `scripts/mac/VERIFY_MAC.command` |
| Mac 备份 | `scripts/mac/BACKUP_MAC.command` |
| Mac 修复 | `scripts/mac/REPAIR_MAC.command` |
| Mac 回滚 | `scripts/mac/ROLLBACK_MAC.command` |
| Windows 检测并安装模型 | `windows\bootstrap\RUN_WINDOWS_SETUP.vbs` |
| Windows 仅验证 | `windows\bootstrap\VERIFY_WINDOWS_SETUP.vbs` |

任何报告出现 `hash-mismatch`、`PROTECTED_MUTATION_DENIED`、`MODEL_MISSING` 或 `SERVICE_UNAVAILABLE` 时，先保留报告和日志，不要手工移动原始数据。
