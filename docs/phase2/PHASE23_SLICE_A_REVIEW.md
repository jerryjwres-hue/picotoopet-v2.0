# Phase 2.3 Slice A 审查结论

## Decision

**Slice A Review Gate: PASS.**

该结论仅覆盖 Control Center 基础壳、能力协商、状态同步、冻结合同、托盘生命周期、Windows 原生 CI、预编译交付链和实机安装验证。它不表示完整 Phase 2.3、Generic Connector、Media Worker、外部 Provider 或 Dev Broker 已完成。

## Reviewed Commit

- 分支：`feature/phase-2.3-slice-a-foundation`
- 审查前提交：`3c36e74e49ac6dbeb7b65ae03401a03aac27632d`
- 基线：`feature/phase-2.3-control-center-design@d59021e3bce20152822c0a4dccad7675e506a068`
- Draft PR：`#2`

## Fresh CI Evidence

提交 `3c36e74e49ac6dbeb7b65ae03401a03aac27632d` 的三条门均通过：

- Phase 2.3 Control Center Validation：Run `30724563829`，PASS；
- Phase 2 Windows Prebuilt Release：Run `30724563830`，PASS；
- Windows Control Center CI：Run `30724563857`，PASS。

Windows Control Center CI 在 `windows-2025` 上完成：合同与安全测试、Core smoke、WPF warnings-as-errors、Shell self-test、预编译打包、Windows PowerShell 5.1 包级复验和 Artifact 上传。

## Field Installation Evidence

用户在真实中文 Windows PC 上完成 `slice-a-10` 安装：

- 安装报告：`status=pass`；
- `source_build_on_user_pc=false`；
- `error=null`；
- Windows 与 Mac Core `2.2.0-phase2-slice1` 完成局域网配对；
- Control Center 显示 `在线`，真实任务快照可见。

首次 `slice-a-4` 安装暴露 Windows PowerShell 5.1 默认编码读取 UTF-8 无 BOM JSON 的缺陷。修复后：

- 所有机器 JSON 使用显式严格 UTF-8 读取；
- 安装器增加 `-PreflightOnly`；
- 原生 Windows 发布门真实执行安装器清单解析和逐文件哈希校验；
- `slice-a-10` 实机安装成功。

## Review Findings

### Passed

- 2.2 REST、WebSocket、Credential Manager 和安装/回滚路径保持兼容；
- 未声明能力默认关闭，不按版本号猜测；
- 事件重复和序号跳跃有明确处理；
- Connector/Handoff Schema 封闭、版本化并包含攻击 fixture；
- 关闭到托盘与显式退出资源释放边界清晰；
- Windows PC 不编译源码、不安装 SDK；
- 没有 Provider 调用、自动上传、自动 push/merge/release 或系统级修改。

### Accepted Limitations

- Task Center 仍为解释性页面，真实任务仅在 Overview 可见；
- Mac Core 具备耐久队列和 `lease_next()`，但没有常驻任务 Worker；
- 因此历史 `Queued` 任务不会自动进入 `Running`；
- Dashboard、Results、Approvals、Detailed Health 和 Logs Query 尚未实现；
- CI 包仍为 `unsigned-ci`。

## Next Authorized Slice

下一纵向批次固定为 **Phase 2.3 Slice B — Dashboard and Task Center**：

1. 真实 Task Center 列表、筛选、详情和安全动作；
2. 明确显示 `Worker unavailable` / `等待执行器`；
3. Dashboard 使用真实快照，不伪造进度或结果；
4. Mac Core 增加只读 Worker 状态合同；
5. 原生 Windows CI、安装包、SHA-256、自检和回滚证据。

Slice B 不在用户 PC 上编译，不修改 `main`，不安装 Mac Worker，不调用外部 Provider。
