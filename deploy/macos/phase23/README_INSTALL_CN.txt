Picotoo Pet V2 — Phase 2.3 Slice D Mac Core 增量包

用途
====
本包把现有 Mac Core 升级到 Slice D 固定诊断 API，并保留已部署的 Slice C Worker 状态。
它不会单独安装 Worker，也不会领取或改写历史 analysis 任务。

安装前提
========
1. 已存在可工作的 PicotooPetV2 Mac Core。
2. current/.venv/bin/python 必须为 Python 3.12。
3. 安装包架构必须与本机一致；当前正式候选面向 Apple Silicon M4 / arm64。
4. 完整解压后再双击脚本，不要从压缩包预览窗口内执行。

安装
====
双击：INSTALL_MAC_CORE_SLICE_B.command

安装器会：
- 验证发布清单、文件大小、SHA-256、架构和唯一项目 wheel；
- 使用包内 wheelhouse 离线创建新虚拟环境；
- 在临时目录和临时端口验证候选 API；
- 验证固定诊断创建端点和任务关联结果端点；
- 保留现有数据库、结果、日志、端口、Keychain 令牌和 Worker 状态；
- 候选通过后才原子切换 current；
- 仅重启当前用户的 com.picotoopet.mac-core LaunchAgent；
- 激活失败时自动恢复上一版本。

验证
====
双击：VERIFY_MAC_CORE_SLICE_B.command

通过条件：
- health.status == ok
- capabilities.features.worker_status == true
- capabilities.features.local_worker == true
- workers.status 可读取；允许 not_deployed、starting、online、degraded 或 offline
- 如果 Worker 为 online，则 available 必须为 true
- OpenAPI 包含：
  /api/v1/tasks/system-diagnostic-snapshot
  /api/v1/tasks/{task_id}/result

回滚
====
双击：ROLLBACK_MAC_CORE_SLICE_B.command

回滚只切换到 state/previous-version.txt 记录的版本，不删除失败版本、数据库、结果或日志。

明确不会执行
============
- 不使用 sudo；
- 不修改防火墙或系统 LaunchDaemon；
- 不删除或迁移 SQLite；
- 不轮换 Keychain API 令牌；
- 不联网解析 Python 依赖；
- 不在用户电脑编译源码；
- 不领取或运行历史 analysis 任务；
- 不调用外部 Provider，不上传数据，不产生付费调用。

看到以下标记才算成功：
PHASE23_MAC_SLICE_D_CORE_INSTALL=PASS
PHASE23_MAC_SLICE_D_CORE_VERIFY=PASS
