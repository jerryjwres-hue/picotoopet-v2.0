Picotoo Pet V2 — Mac Core Phase 2.3 Slice B 增量包

用途
====
本包只把 Mac Core 升级到 2.3.0 Slice B，并公开只读 Worker 状态合同。
它不会安装或启动任务 Worker，也不会自动执行历史 Queued 任务。

安装前提
========
1. 已存在可工作的 PicotooPetV2 Mac Core 2.2 安装。
2. current/.venv/bin/python 必须为 Python 3.12。
3. 安装包架构必须与本机一致：Apple Silicon 使用 arm64，Intel 使用 x86_64。
4. 完整解压后再双击脚本，不要从压缩包预览窗口内执行。

安装
====
双击：INSTALL_MAC_CORE_SLICE_B.command

安装器会：
- 验证发布清单、文件大小和 SHA-256；
- 使用包内 wheelhouse 离线创建新虚拟环境；
- 在临时目录和临时端口验证候选 API；
- 保留现有数据库、结果、日志、端口和 Keychain 令牌；
- 候选通过后才原子切换 current；
- 仅重启当前用户的 com.picotoopet.mac-core LaunchAgent；
- 失败时自动恢复上一版本。

验证
====
双击：VERIFY_MAC_CORE_SLICE_B.command

通过条件：
- health.status == ok
- capabilities.features.worker_status == true
- capabilities.features.local_worker == false
- workers.status.state == not_deployed
- workers.status.available == false

回滚
====
双击：ROLLBACK_MAC_CORE_SLICE_B.command

回滚只切换到 state/previous-version.txt 记录的版本，不删除失败版本、数据库或日志。

明确不会执行
============
- 不使用 sudo；
- 不修改防火墙或系统 LaunchDaemon；
- 不删除或迁移 SQLite；
- 不轮换 Keychain API 令牌；
- 不联网解析 Python 依赖；
- 不安装 Worker；
- 不领取或运行历史任务；
- 不调用外部 Provider，不上传数据，不产生付费调用。
