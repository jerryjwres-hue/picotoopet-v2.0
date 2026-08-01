# 回滚指南

## Mac

升级或修复前先双击：

```text
scripts/mac/BACKUP_MAC.command
```

回滚时双击：

```text
scripts/mac/ROLLBACK_MAC.command
```

回滚程序会停止当前两个 launchd 服务、读取 `state/previous_version.txt`、原子切换 `current` 链接并重新加载服务。数据库备份采用 SQLite `.backup`，不会直接复制正在写入的 WAL 文件组合。

## Windows

Windows 安装器对现有 `%APPDATA%\ComfyUI\extra_models_config.yaml` 先生成时间戳备份。需要撤销外部模型配置时：

1. 关闭 Comfy Desktop。
2. 把最近的 `extra_models_config.yaml.backup-*` 恢复为 `extra_models_config.yaml`。
3. 重新启动 Comfy Desktop。

模型文件不会覆盖 Desktop 内置资源。删除 E 盘模型不是常规回滚步骤；应先保留，避免重复下载。哈希错误文件只存在于 `E:\PicotooPet\Quarantine`。
