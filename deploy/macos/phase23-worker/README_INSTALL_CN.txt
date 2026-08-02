Picotoo Pet V2 — Phase 2.3 Slice C Mac Worker 安装说明

适用设备：Apple Silicon M4 / arm64
前置版本：已通过 INSTALL 与 VERIFY 的 Mac Core 2.3.0 Slice B

本包会：
1. 校验发布清单、文件大小和 SHA-256；
2. 使用包内 wheelhouse 离线安装 Mac Core 2.3.0 Slice C；
3. 在临时端口验证候选 Core；
4. 原子切换 current；
5. 验证正式 Core；
6. 写入当前用户的 com.picotoopet.worker LaunchAgent；
7. 启动 Worker 并验证在线状态。

本包不会：
- 使用 sudo；
- 修改防火墙或系统 LaunchDaemon；
- 删除数据库、Token、日志、结果或旧版本；
- 在本机编译源码或联网解析依赖；
- 调用 Provider、上传数据或产生费用；
- 执行历史 analysis 任务。

当前 Worker 只支持无副作用任务类型：system.noop。
已有 analysis 等未知任务仍保持 Queued。

安装：双击 INSTALL_MAC_WORKER_SLICE_C.command
验证：安装 PASS 后双击 VERIFY_MAC_WORKER_SLICE_C.command
回滚：只有验证失败或 Core/Worker 异常时，双击 ROLLBACK_MAC_WORKER_SLICE_C.command

报告目录：
~/Library/Application Support/PicotooPetV2/reports

看到以下标记才算成功：
PHASE23_MAC_WORKER_INSTALL=PASS
PHASE23_MAC_WORKER_VERIFY=PASS
