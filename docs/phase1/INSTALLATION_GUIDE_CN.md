# 安装指南

## Mac mini

1. 将交付 ZIP 解压到 Mac 本地普通目录。
2. 双击 `scripts/mac/INSTALL_MAC.command`。
3. 安装器会创建带 UTC 时间和进程标识的独立版本目录、安装 `uv` 依赖、生成 Keychain API Token、写入两个 launchd 服务并执行基础健康检查；重复安装和修复不会覆盖上一版本。
4. 双击 `scripts/mac/VERIFY_MAC.command`。验证报告必须显示：SQLite 正常、两个 launchd 服务存在、REST 健康接口可访问、`gpt-oss:20b` 为 `resident`。

安装目标：

```text
~/Library/Application Support/PicotooPetV2/
```

API Token 只存入当前用户 macOS Keychain，服务 plist、日志和 SQLite 中不保存明文。

## Windows 11

1. 将同一交付包解压到 Windows 普通目录。
2. 关闭正在编辑但尚未保存的 ComfyUI 工作流。
3. 双击 `windows\bootstrap\RUN_WINDOWS_SETUP.vbs`。
4. 程序会自动：
   - 检测 `C:\zhaoyang lin\opc\Comfy Desktop`；
   - 检测 AppData 和常见数据目录；
   - 检测 ComfyUI API、NVIDIA 驱动和磁盘；
   - 创建 `E:\PicotooPet\Models`；
   - 备份并增量更新 `%APPDATA%\ComfyUI\extra_models_config.yaml`；
   - 使用固定版本 `huggingface_hub` 和稳定暂存目录断点下载固定提交版本模型；
   - 校验 SHA-256；
   - 把不匹配文件移入 `E:\PicotooPet\Quarantine`；
   - 打开 HTML 报告。
5. 模型全部显示 `installed_verified` 或 `already_verified` 后，重新启动一次 Comfy Desktop，使外部模型路径生效。

模型不会写入 `Comfy Desktop\resources\ComfyUI`。模型暂存、正式目录和隔离区均位于 E 盘。

## 模型清单

- Wan2.2 TI2V-5B FP16：主视频生成。
- Wan2.1 VACE-1.3B FP16：主视频编辑。
- UMT5 XXL FP8：共享文本编码器。
- Wan2.2 VAE。
- Wan2.1 VAE。

交付包不内嵌模型权重，安装器会在 Windows 实机联网下载并逐文件校验。`VERIFY_WINDOWS_SETUP.vbs` 是只读验证入口：它不会创建模型目录、安装下载工具、隔离文件或修改 ComfyUI 配置。

## Mac API 端口自动处理

- 首次安装优先使用 `8765`。
- 如果检测到 `8765` 已被旧 PicotooPetAI 服务占用，V2 自动使用 `8766`。
- 实际端口记录在：

```text
~/Library/Application Support/PicotooPetV2/state/api-port.txt
```

- `VERIFY_MAC.command` 会读取该记录，不再写死 `8765`。
- 已安装旧版且出现端口冲突时，双击 `scripts/mac/REPAIR_MAC_PORT_CONFLICT.command`。该修复只迁移 V2，不会停止、删除或修改旧服务，并会在失败时恢复修复前配置。
