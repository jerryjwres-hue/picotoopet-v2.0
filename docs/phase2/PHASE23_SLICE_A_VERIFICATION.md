# Phase 2.3 Slice A 验证报告

## Scope

本报告仅覆盖 Phase 2.3 Slice A：Control Center 基础能力、版本化合同、Windows 状态同步、冻结导航、WPF Shell、解释性空状态、Credential Manager 配对兼容、关闭到托盘，以及原生 Windows CI/预编译包链路。

本报告不表示完整 Phase 2.3 发布完成，不包含 Slice B Dashboard/Task Center 深化、外部 Provider、Dev Broker、Windows Worker、自动化执行器或 Protected 数据处理。

## Source Commit

- 被测分支：`feature/phase-2.3-slice-a-foundation`
- 被测分支提交：`46594db88737b78700b8af88c41bff4e50eeb248`
- Draft PR：`#2`
- GitHub Actions PR merge ref：`68fd9c30f0c6f7d7d78f7794c14b471b345f05b0`
- 基线提交：`4ef2634ec24666d8995874d44bbf5b0e238d450a`
- 验证日期：`2026-08-01 UTC`

GitHub Actions 对 PR merge ref 执行测试；该 merge ref 将被测分支提交合入冻结设计分支，仅用于 CI，不代表已合并 `main`。

## Python Tests

### 完整回归门

- Workflow：`Phase 2.3 Control Center Validation`
- Run ID：`30719702439`
- Runner：Ubuntu 24.04
- Python：3.12.13
- 能力合同聚焦测试：`1 passed`
- 完整测试：`162 passed in 3.35s`
- Ruff：`All checks passed!`
- OpenAPI：确定性导出后与仓库版本一致
- 结果：PASS

### Windows 合同与安全测试

- Workflow：`Windows Control Center CI`
- Run ID：`30719702441`
- Runner：Microsoft Windows Server 2025, `10.0.26100`
- Python：3.12.10
- 合同与安全测试：`77 passed, 2 skipped in 2.70s`
- 两项跳过均为必须实际执行 macOS `launchctl`/`open` 或 source POSIX shell helper 的运行时测试；它们在 Ubuntu 完整回归门中执行，不在 Windows 上伪造结果。
- 结果：PASS

## Windows Core Smoke

- 项目：`PicotooPet.Desktop.Core.SmokeTests`
- Marker：`PHASE2_CORE_SMOKE=PASS`
- 覆盖：能力反序列化、Legacy 2.2 降级、独立状态仓库、重复事件去重、序号跳跃检测、REST 有界重载、冻结导航及解释性文案
- 结果：PASS，退出码 0

## Native Windows Build

### Control Center 专用门

- Workflow：`Windows Control Center CI`
- Run ID：`30719702441`
- Job ID：`91421305225`
- Runner image：`windows-2025-vs2026`
- Runner image version：`20260728.188.1`
- .NET SDK：`10.0.302`
- MSBuild：`18.6.11+35b593beb`
- RID：`win-x64`
- Solution build：成功
- Warnings：0
- Errors：0
- Desktop marker：`PHASE2_DESKTOP_SELF_TEST=PASS`
- Control Center marker：`PHASE23_CONTROL_CENTER_SELF_TEST=PASS`
- Diagnostics marker：`PHASE2_DIAGNOSTICS_SELF_TEST=PASS`
- 结果：PASS

### 稳定 Phase 2 预编译发布门

- Workflow：`Phase 2 Windows Prebuilt Release`
- Run ID：`30719702454`
- Windows build/self-test/package/PowerShell 5.1 verify/artifact upload：全部 PASS
- 该门确认新增 Slice A 代码未破坏现有 Phase 2 Windows 预编译链路。

## Packaging and SHA-256

- Artifact name：`windows-control-center-4`
- Artifact ID：`8824540202`
- Artifact retention：14 days
- Artifact archive SHA-256：`8a43c14fbfd9ad83aab733e228bcf28e824458db5fd13900bab38c52937b230b`
- Artifact archive size：`109186566` bytes

预编译包：

- 文件：`PicotooPet-Phase2-Windows-Prebuilt-2.3.0-slice-a-4-68fd9c30f0c6f7d7d78f7794c14b471b345f05b0.zip`
- 大小：`109859476` bytes
- SHA-256：`1d74a9e5bb2c32501ade79ca93b3acccfaefcd31a2802f20ab9dc2716a98511e`
- Build report status：`pass`
- File count：2
- Signature status：`unsigned-ci`

SHA-256 已通过三路一致性校验：CI 生成的 `.sha256.txt`、`windows-build-report.json` 的 `package_sha256`、下载后本地 `sha256sum` 均为上述值。

包级 Windows PowerShell 5.1 复验 Marker：`PHASE2_WINDOWS_RELEASE_TEST=PASS`。

## Security and Redaction

- 设备令牌仍通过 `CredentialManagerTokenStore` 写入 Windows Credential Manager；`settings.json` 只保存非敏感 Mac 地址。
- Shell 的 PasswordBox 密文只由视图转交 `ControlCenterSession`，不会进入 `ShellViewModel`、日志或设置文件。
- `SafeFileLogger` 自检结果：`pass`；Bearer/长 Token 脱敏检查通过。
- 合同 Schema 使用封闭结构；Connector 路径逃逸、Handoff Protected 数据和沙盒越界反例均由测试拒绝。
- Capability 404、无效或不完整响应均保守降级为 Legacy 2.2，不会默认启用未实现功能。
- 本切片未加入外部 Provider 调用、Worker 执行、自动上传、自动发布或自动合并。

## 2.2 Compatibility

- 现有 Mac Core URL 和设备 Token 配对行为保留。
- REST、WebSocket 和 Credential Manager 路径保留。
- Legacy 2.2 能力集仍允许 Task Center/耐久任务列表。
- 未实现的 Dashboard、Results、Approvals、Cloud Development、Automation、Health detailed 和 Logs query 均保持关闭并显示原因。
- 旧 `MainWindow` 保留为编译兼容面；运行时组合根已切换到 `ControlCenterSession`、`ShellViewModel` 和 `ShellWindow`。
- 稳定 Phase 2 Windows 发布门在同一被测提交上通过。

## Not Run / User Waived

以下项目未执行，因此不得据此宣称完整发布或实机可用性已经最终确认：

- 未在用户 PC 上安装、启动或修改系统配置；用户要求前期只在 GitHub/隔离环境测试。
- 未执行真实 Mac 与用户 Windows PC 的端到端配对、断网重连和长时间运行。
- 未进行人工视觉验收、屏幕缩放/多显示器/辅助功能验收。
- 未进行正式代码签名；当前包明确标记为 `unsigned-ci`。
- 未进行自动发布、Release 创建、`main` 合并或生产安装。
- 未安装或调用外部 Provider、Dev Broker、Grok Build、Windows Worker 或 Media Worker。

## Rollback Evidence

预编译包包含：

- `ROLLBACK_PHASE2_WINDOWS.vbs`
- `Rollback-Phase2Prebuilt.ps1`
- `VERIFY_PHASE2_WINDOWS.vbs`
- `Verify-Phase2Prebuilt.ps1`
- `INSTALL_PHASE2_WINDOWS.vbs`
- `Install-Phase2Prebuilt.ps1`

Windows PowerShell 5.1 包级门对安装、验证和回滚 PowerShell 脚本执行了解析器语法检查；包清单逐文件校验 SHA-256 和大小；应用与诊断器均从解压后的真实包载荷执行 self-test。

普通窗口关闭只隐藏到内置 `NotifyIcon` 托盘；显式退出先解除订阅并释放 `ShellViewModel`、`ControlCenterSession`、连接池、日志器和托盘句柄，再调用 WPF `Shutdown()`。

## Final Slice A Status

**Phase 2.3 Slice A CI verification: PASS.**

该状态表示冻结范围内的源码、合同、原生 Windows build、self-test、预编译打包、SHA-256 和 Windows PowerShell 5.1 包复验均通过。它不表示完整 Phase 2.3 已发布，也不授权合并 `main`、正式发布或在用户 PC 上安装。

下一步仅进入 Slice A Review Gate；在审查完成前停止 Slice B。
