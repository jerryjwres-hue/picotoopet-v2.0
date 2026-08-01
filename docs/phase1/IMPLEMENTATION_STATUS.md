# Picotoo Pet V2 — Phase 1 实施状态

## 已实现

- `uv` Python 项目结构和可安装控制台入口。
- SQLite WAL 耐久数据库、迁移、幂等任务队列、优先级租约和崩溃恢复。
- 冻结任务状态机；终态任务重试会创建子任务，不会重开原记录。
- Protected 默认拒绝权限门、路径穿越与符号链接逃逸防护。
- 脱敏、追加式、SHA-256 哈希链审计日志。
- 原子内容寻址 Result Store。
- 一次性、限时审批令牌；云端任务固定停在 `WaitingForApproval`。
- REST API、统一错误外壳、认证 WebSocket、Outbox。
- PydanticAI Ollama Runtime 延迟装配，使用当前 `OllamaModel + OllamaProvider(/v1)` 契约。
- `gpt-oss:20b` Resident Manager，使用永久常驻策略；缺失时只报告，不擅自下载。
- 健康监督器和 launchd 服务模板。
- 冻结 MCP 工具注册表和受控执行适配器，不提供任意 Shell/文件工具。
- Phase 0 只读盘点器。
- Windows ComfyUI 检测、外部 E 盘模型路径配置、固定版本模型下载、SHA-256 校验、错误文件隔离和无终端 VBS 入口。
- Windows 模型下载器固定使用 `huggingface_hub==1.24.0`，按提交版本下载，使用稳定暂存目录断点续传；`VerifyOnly` 模式不创建、移动或修改模型文件。
- Mac 双击安装、验证、备份、修复和回滚入口。
- JSON Schema、OpenAPI、MCP 契约导出。

## 本地自动验证

当前交付源码在隔离仓库中通过 **71 项 pytest 测试，0 失败**。测试覆盖配置、迁移、状态机、权限、路径策略、审计链、Result Store、队列、审批、事件、Ollama、PydanticAI 适配、REST、WebSocket、健康监督、MCP、Phase 0 盘点、Windows 脚本契约、Mac 部署契约和导出契约。发布扫描同时确认 133 个源码文件中没有已知明文密钥、缺失必需文件或格式错误的模型哈希。

## 尚需目标机器验证

当前构建环境不是 macOS 或 Windows，且不具备目标局域网与 GPU。因此以下项目必须由交付包在实机验证：

- `launchctl bootstrap`、Keychain 和真实 Ollama API。
- Comfy Desktop 的真实数据目录和 API。
- RTX 5070 Ti 上模型加载、首帧生成、显存峰值和断点恢复。
- PowerShell 5.1 脚本的实机执行。
- 大模型实际下载；交付 ZIP 不内嵌约数十 GB 的权重。

在这些报告通过之前，Phase 1 状态应表述为“源码与契约验证完成，实机验收待执行”，不能表述为生产部署完成。

## Mac 端口冲突实机修复

实机诊断确认旧平台 `~/PicotooPetAI/Platform/Server/picotoo_server.py` 已监听 `8765`。Phase 1 安装器现会在首次安装时自动从 `8765`、`8766` 中选择空闲端口并持久化；验证器读取实际端口并要求 launchd 状态为 `running`。另提供可回滚的一键端口迁移脚本，修复过程不修改旧平台进程或 Protected 数据。
