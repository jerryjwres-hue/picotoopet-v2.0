Picotoo Pet V2 — Phase 2.3 Slice D Mac Worker 安装说明

适用设备：Apple Silicon M4 / arm64
前置条件：Mac Core 已安装且可通过健康检查；建议先安装同批次 Slice D Core 包。

本包会：
1. 校验发布清单、文件大小、SHA-256、架构和唯一项目 wheel；
2. 使用包内 wheelhouse 离线安装同批次 Core + Worker Runtime；
3. 在临时端口验证候选 Core、Worker 状态 API 和诊断固定端点；
4. 备份现有 Worker LaunchAgent 定义和 current 指针；
5. 原子切换 current；
6. 写入当前用户的 com.picotoopet.worker LaunchAgent；
7. 启动 Worker，并验证固定支持类型和空闲状态。

Worker 固定支持：
- system.noop
- system.diagnostic_snapshot

系统诊断任务：
- 只读取 Core/Worker/Queue 的非敏感公开状态；
- 不读取文件清单、日志正文、Token、IP、项目内容或用户文档；
- 不访问网络，不调用 Provider，不产生费用；
- 结果为固定 JSON 合同，最大 64 KiB；
- 单任务执行，硬超时 30 秒；
- 取消或超时后最多等待 5 秒清理子进程，随后强制回收；
- 不领取或改写历史 analysis 任务。

本包不会：
- 使用 sudo；
- 修改防火墙或系统 LaunchDaemon；
- 删除数据库、Token、日志、结果或旧版本；
- 在用户电脑编译源码或联网解析依赖；
- 动态加载任意任务处理器。

安装：双击 INSTALL_MAC_WORKER_SLICE_C.command
验证：安装 PASS 后双击 VERIFY_MAC_WORKER_SLICE_C.command
回滚：仅在验证失败或 Core/Worker 异常时，双击 ROLLBACK_MAC_WORKER_SLICE_C.command

报告目录：
~/Library/Application Support/PicotooPetV2/reports

看到以下标记才算成功：
PHASE23_MAC_WORKER_SLICE_D_INSTALL=PASS
PHASE23_MAC_WORKER_SLICE_D_VERIFY=PASS

安装、验证或回滚任一步失败时，请保留报告文件，不要删除版本目录或数据库。
