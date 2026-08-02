# Phase 2.3 Slice B 验证报告

## Scope

本报告覆盖 Phase 2.3 Slice B：Mac Core Worker 状态合同、Windows Worker 状态同步、真实任务中心、任务筛选与详情、安全取消/重试、Dashboard Worker 摘要、原生 Windows 构建、自检、预编译打包和回滚链。

本报告不表示完整 Phase 2.3 已完成，不包含真实 Mac Worker、Connector 运行时、结果/审批页面、Provider、Dev Broker、自动上传或自动合并。

## Source Commit

- 被测分支：`feature/phase-2.3-slice-b-dashboard-task-center`
- 被测分支提交：`e748d65fbf8a9bcc01c3c802a0b3357793b389a3`
- Draft PR：`#3`
- PR 基线：`feature/phase-2.3-slice-a-foundation@58c2bc2ea900dc8ca72a1628e47f1a079a50b344`
- GitHub Actions PR merge ref：`2ec01b4e92561144e29da9c0b3528f4d89bccc55`
- 验证日期：`2026-08-02 UTC`

GitHub Actions 对 PR merge ref 执行最终测试；该 merge ref 仅用于验证 Slice B 与 Slice A 的组合，不代表已合并 `main`。

## Python and Contract Verification

- Workflow：`Phase 2.3 Control Center Validation`
- Run ID：`30727298243`
- Job ID：`91441242272`
- Runner：Ubuntu 24.04.4，image `20260720.247.2`
- Python：3.12.13
- Capabilities + Worker 聚焦合同：`3 passed in 0.53s`
- 完整 Python 回归：`169 passed in 2.56s`
- Ruff：`All checks passed!`
- OpenAPI：确定性重新导出后 `git diff --exit-code` 通过
- OpenAPI Artifact ID：`8826783300`
- OpenAPI Artifact SHA-256：`b944e7f28663ce4fde773908a414dd93c3229b81a64a0a74b3c602c2b3cfe9e1`
- 结果：PASS

## Worker Contract and Non-Execution Boundary

Mac Core 现在公开只读、需要设备认证的：

```text
GET /api/v1/workers/status
```

冻结默认响应：

```json
{
  "schema_version": "2.3.0",
  "available": false,
  "state": "not_deployed",
  "reason": "worker_runtime_not_installed",
  "worker_id": null,
  "supported_task_types": []
}
```

能力合同明确区分：

```text
worker_status = true
local_worker = false
windows_worker = false
```

Slice B 未增加 `lease_next()` 消费循环、常驻 Worker、历史任务自动领取、自动重试执行或模型任务执行。现有 `Queued` 记录不会因安装 Windows 包而开始运行。

旧 Mac Core 2.2 不存在 Worker 状态端点时，Windows 客户端对 HTTP 404 保守降级为 `not_deployed`，因此 Windows Slice B 可以先连接现有 Mac 2.2。

## Native Windows Build

### Control Center 专用门

- Workflow：`Windows Control Center CI`
- Run ID：`30727298256`
- Job ID：`91441251531`
- Runner label：`windows-2025`
- OS：Microsoft Windows NT `10.0.26100.0`
- .NET SDK：`10.0.302`
- Core smoke：PASS
- WPF solution build with warnings-as-errors：PASS
- Control Center self-test：PASS
- Task Center self-test：PASS
- Slice B package build：PASS
- Windows PowerShell 5.1 package verification：PASS
- Artifact upload：PASS

### Stable Phase 2 compatibility gate

- Workflow：`Phase 2 Windows Prebuilt Release`
- Run ID：`30727298265`
- Job ID：`91441252604`
- Native build, analysis, publish, self-test, PowerShell 5.1 verification and artifact upload：全部 PASS

该门证明 Slice B 没有破坏原有 Phase 2 预编译交付路径。

## Task Center Verification

任务中心现在使用真实 Mac Core 耐久队列，并包含：

- 全部、活动任务、等待执行器、已完成、失败或已取消筛选；
- 虚拟化与 recycling 列表；
- 任务 ID、任务类型、原始状态、用户状态、创建/更新时间、尝试次数、优先级、超时和错误；
- `Queued + Worker unavailable` 显示为“等待执行器”；
- 取消动作只对冻结状态机允许的非终态启用；
- 取消前显示 Yes/No 确认，默认 No；
- 重试只对 Failed/Cancelled 启用，并调用服务端创建新的子任务，不重新打开原任务；
- Dashboard 显示真实 Worker 状态和等待执行器数量。

## Package and SHA-256

GitHub Actions Artifact：

- Artifact name：`windows-control-center-slice-b-58`
- Artifact ID：`8826870413`
- Artifact archive size：`109223673` bytes
- Artifact archive SHA-256：`00e919a4f69f4bc4d0cfb1af6c1c0b52aac796ef2dc3986edf475e535a0b6456`
- Retention：14 days

预编译安装包：

- 文件：`PicotooPet-Phase2-Windows-Prebuilt-2.3.0-slice-b-58-2ec01b4e92561144e29da9c0b3528f4d89bccc55.zip`
- 大小：`109897111` bytes
- SHA-256：`4475e2313d1fd49ae1e0b8d4a6e6ef4cb2db0970d3abca3d5be24458653d0c80`
- Target：`win-x64`
- Signature：`unsigned-ci`
- Source build on user PC：false

载荷文件独立复算结果：

- `Picotoo Pet AI.exe`
  - size：`191203583` bytes
  - SHA-256：`a7324ec219e518d3884622573d490b687f101a82415c3035e55d9c6e6ce10bc2`
- `tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe`
  - size：`83709989` bytes
  - SHA-256：`fde22b1b95ba77a5f0589e976b930f0d36332ff896b51cfee72797ad4cc6b52e`

安装包 SHA-256 已通过：CI `.sha256.txt`、`windows-build-report.json`、下载后独立重算三路一致性校验。

## Packaged Self-Test

真实发布载荷中的自检报告状态为 `pass`，以下六项全部通过：

```text
safe_logger
client_options
task_center_policy
control_center_shell
worker_fallback
filesystem_cleanup
```

包级 PowerShell 5.1 复验同时检查：

- release manifest UTF-8 解析；
- manifest 相对路径、文件大小和 SHA-256；
- 安装器 `-PreflightOnly`；
- VBS 无 UTF-8 BOM；
- 主程序与诊断器真实 EXE self-test；
- Task Center 和 Worker fallback markers；
- 安装、验证、回滚脚本语法。

## Security and Data Boundaries

- Windows 设备令牌仍只保存于 Credential Manager；
- settings 文件只保存非敏感 Mac 地址；
- 日志继续执行 Bearer/长 Token 脱敏；
- 安装包不修改防火墙、PATH、系统服务、系统级注册表、ComfyUI 或模型目录；
- 取消和重试均通过 Mac Core 受认证 API，并由服务端冻结状态机裁决；
- 未加入 Provider、上传、费用、自动发布、自动合并或 Protected 数据操作；
- 未加入 Worker 执行或历史任务消费。

## Rollback Evidence

安装包包含：

```text
INSTALL_PHASE2_WINDOWS.vbs
Install-Phase2Prebuilt.ps1
VERIFY_PHASE2_WINDOWS.vbs
Verify-Phase2Prebuilt.ps1
ROLLBACK_PHASE2_WINDOWS.vbs
Rollback-Phase2Prebuilt.ps1
README_INSTALL_CN.txt
```

安装器保留上一版本指针；失败时不会把用户 PC 变成源码构建环境。回滚只恢复上一预编译版本并重建用户级快捷方式/启动项。

## Code Review

审查覆盖 Worker 合同、状态同步、任务状态解释、取消/重试动作、WPF 绑定、包级 self-test 和交付脚本。冻结任务状态机允许的取消边界与 Windows `CanCancel` 规则一致；Failed/Cancelled 重试继续创建新任务。

已确认没有：

- Worker 消费循环；
- 自动处理历史 Queued 任务；
- Provider 调用或外部上传；
- Token 日志；
- `main` 写入；
- 自动 merge/release；
- 用户 PC 源码构建指令。

## Not Run / User Validation Required

以下项目尚未执行，因此不得表述为已完成：

- 新 Slice B 包尚未在用户 Windows PC 上安装；
- 未在真实 Windows + Mac 长时间运行；
- 未升级用户 Mac Core 到显式 Worker 状态接口；当前 Windows 会对旧 Mac 2.2 使用 404 保守降级；
- 未部署真实 Mac Worker；
- 未进行正式代码签名；SmartScreen 仍可能提示未知发布者；
- 未合并 `main`，未创建正式 Release。

## Final Status

**Phase 2.3 Slice B Windows candidate verification: PASS.**

该状态表示 Slice B 的源码、合同、OpenAPI、169 项 Python 回归、原生 Windows Core smoke、严格 WPF 构建、Task Center self-test、self-contained 预编译包、SHA-256 和 Windows PowerShell 5.1 包级复验均通过。

它不表示完整 Phase 2.3 已发布，也不授权合并 `main`。下一步是在用户 Windows PC 安装该候选包并进行实机任务中心验收；Mac Core 增量交付在独立分支 `feature/phase-2.3-slice-b-mac-core-delta` 继续构建。
