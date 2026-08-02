# Phase 2.3 Slice B — Mac Core 增量交付状态

更新时间：2026-08-02

## 目标

为现有 Mac Core 2.2 安装提供架构专属、离线、可回滚的 Slice B 增量包，使 Windows Control Center 能读取真实 `/api/v1/workers/status`，同时明确保持 Worker 未部署，历史 `Queued` 任务不会自动执行。

## 事实路径决策

原计划草案曾写入：

```text
~/Library/Application Support/PicotooPetV2/mac-core
```

现有 LaunchAgent 和已部署安装器的事实路径是：

```text
~/Library/Application Support/PicotooPetV2
├── current -> versions/<active-version>
├── versions/
├── data/
├── state/api-port.txt
├── logs/
└── reports/
```

本增量包必须沿用现有事实路径，不能另建第二个 `mac-core/current`。否则现有 `com.picotoopet.mac-core` LaunchAgent 不会使用新版本，并可能形成两个事实源。

CI 隔离夹具通过 `PICOTOO_RUNTIME_ROOT_OVERRIDE` 使用临时目录；真实安装默认值始终是现有用户级根目录。

## 已实现

### 版本身份

- Wheel：`picotoopet-core==2.3.0.dev1`
- 运行时健康版本：`2.3.0-slice-b`
- API Schema：`2.3.0`

### 原生架构包

GitHub Actions 在以下原生 Runner 独立构建：

- `macos-15` / `arm64`
- `macos-15-intel` / `x86_64`

每个包包含：

```text
release-manifest.json
payload/wheelhouse/*.whl
INSTALL_MAC_CORE_SLICE_B.command
VERIFY_MAC_CORE_SLICE_B.command
ROLLBACK_MAC_CORE_SLICE_B.command
lib.sh
README_INSTALL_CN.txt
```

用户 Mac 只从 wheelhouse 安装，不下载依赖、不编译源码、不运行 `uv lock`。

### 安装事务

安装器按以下顺序执行：

1. 验证 tar 外层 SHA、发布清单、每个文件的大小和 SHA-256；
2. 确认架构匹配；
3. 确认现有 `current/.venv/bin/python` 为 Python 3.12；
4. 读取并保留 `state/api-port.txt`；
5. 从现有 Keychain 项读取 API Token，不输出、不写报告；
6. 记录当前版本到 `state/previous-version.txt`；
7. 创建新的 `versions/<version>-<arch>`；
8. 仅使用 `--no-index --find-links` 从包内 wheelhouse 安装；
9. 在临时运行目录和临时端口启动候选；
10. 验证 health、capabilities 和认证后的 Worker 状态；
11. 候选全部通过后才原子切换 `current`；
12. 只重启 `gui/$UID/com.picotoopet.mac-core`；
13. 验证现有配置端口；
14. 激活后失败时自动恢复旧 symlink 并重启旧服务。

### Worker 安全状态

安装后必须满足：

```text
capabilities.features.worker_status == true
capabilities.features.local_worker == false
workers.status.state == not_deployed
workers.status.available == false
```

本切片明确不包含：

- `lease_next()`；
- `recover_expired_leases()`；
- Worker 循环、租约续期或任务执行；
- 历史任务自动领取；
- Provider、上传或付费调用。

### 隔离夹具

原生 CI 在临时目录中完成：

1. 建立基线版本和临时 `current`；
2. 启动临时 Mac Core；
3. 创建一个真实 `Queued` 任务并记录 `updated_at`；
4. 停止临时服务；
5. 运行离线安装器；
6. 验证新 API 合同；
7. 再次读取该任务；
8. 确认状态仍为 `Queued` 且 `updated_at` 未变化；
9. 运行回滚；
10. 验证回滚后的健康状态；
11. 上传安装、验证、回滚和任务前后快照证据。

## 不修改的内容

- SQLite 数据库和 schema；
- 结果、项目、日志和备份；
- API 端口；
- Keychain Token；
- 健康监督器 LaunchAgent；
- 防火墙、系统 LaunchDaemon、系统 PATH；
- `main` 分支。

## 当前检查点

分支：

```text
feature/phase-2.3-slice-b-mac-core-delta
```

Draft PR：`#4`

当前代码检查点之后必须通过：

- 全量 Python 回归；
- Ruff；
- macOS Bash 语法；
- arm64 wheelhouse 构建和包级复验；
- x86_64 wheelhouse 构建和包级复验；
- 两个架构的隔离安装、Queued 保持和回滚夹具；
- Artifact、SHA-256 和证据检查。

在这些门全部完成前，不把任何包称为用户可安装候选包，也不在真实 Mac 上运行安装器。
