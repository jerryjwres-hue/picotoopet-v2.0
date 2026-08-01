# 验证指南

## Mac 验收

双击：

```text
scripts/mac/VERIFY_MAC.command
```

通过条件：

- `com.picotoopet.mac-core` 和 `com.picotoopet.health-supervisor` 均已被当前用户 launchd 加载。
- `/api/v1/health` 返回 `ok` 或仅有明确、可解释的 `degraded`。
- `resident-check` 返回 `resident`，模型名严格为 `gpt-oss:20b`。
- `core.db` 使用 WAL，重启后已排队任务仍存在。
- 日志不含 API Token。

## Windows 验收

双击：

```text
windows\bootstrap\VERIFY_WINDOWS_SETUP.vbs
```

该入口严格只读：只检测环境、配置和文件 SHA-256，不创建 E 盘目录、不移动错误文件、不下载模型。

查看：

```text
%LOCALAPPDATA%\PicotooPetV2\Reports\windows_setup_report.html
```

通过条件：

- Comfy Desktop 可执行文件被识别。
- `resources\ComfyUI` 标记为 `FORBIDDEN` 修改区。
- 五个模型全部为 `already_verified` 或 `installed_verified`。
- `extra_models_config.yaml` 指向 `E:/PicotooPet/Models`。
- 报告中不存在 `missing` 或 `hash_mismatch`；正式安装模式发现错误哈希时，原文件只能被移入 `Quarantine`。

## 源码验收

在有网络和 `uv` 的开发环境运行根目录 `VERIFY_RELEASE.command`。该入口会导出契约、运行全部测试、执行秘密扫描并生成验证报告。
