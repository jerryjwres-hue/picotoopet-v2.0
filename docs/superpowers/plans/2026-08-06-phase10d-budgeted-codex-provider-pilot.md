# Phase 10D-A 受控低预算 Codex Provider 试点实施计划

> 产品版本：`2.3.13.2`
> 基线：`2.3.13.1` / `65d5ba0ef5a4ac6f6b3ca61b0f852599d1286d6f`
> 规格：`docs/superpowers/specs/2026-08-06-phase10d-budgeted-codex-provider-pilot-design.md`

## 执行原则

- 先 RED、后 GREEN；每个生产行为必须由失败测试驱动。
- Mac Core + SQLite 保持唯一事实源；Windows 只做原生 WPF 控制面；Mac Worker 是唯一真实 Provider 执行面。
- CI 只使用确定性 fake Codex JSONL 协议，不消耗用户额度。
- 不修改 `main`；保持 Draft PR；用户机器不编译源码。
- 不自动充值、重试、commit、push、PR、merge、tag 或 release。

## Task 1：Core 合同与迁移 RED

新增：

- `tests/test_provider_session_schema.py`
- `tests/test_provider_session_service.py`
- `tests/test_provider_session_api.py`

要求先失败并证明：

1. additive migration 建立 `provider_sessions` 与 `provider_usage_confirmations`；
2. migration 可重复执行，不改已有 Handoff/Return/Broker 数据；
3. 人工额度确认绑定 Handoff、request/package digest、Provider、固定预算和 15 分钟过期时间；
4. `confirmed_available` 之外的状态不能启动；
5. 每个 approved Handoff 只能有一个真实 Session；
6. 固定预算为 8 turns、900 秒、5 文件、64 KiB/文件、256 KiB Return、0 自动重试；
7. API `extra=forbid`，拒绝模型、命令、路径、环境变量、凭据和任意 JSON；
8. 安全投影不包含 prompt、transcript、Authorization、Token、Cookie 或 Keychain 内容。

## Task 2：Core 实现

新增：

- `src/picotoopet_core/providers/__init__.py`
- `src/picotoopet_core/providers/models.py`
- `src/picotoopet_core/providers/service.py`
- `src/picotoopet_core/providers/router.py`

修改：

- `src/picotoopet_core/db/schema.py`
- Core FastAPI 组合根和依赖注入文件
- OpenAPI/安全投影合同

实现状态机、幂等、预算账本、取消、Return intake 和固定错误码。

## Task 3：Mac Worker Adapter RED

新增：

- `tests/test_codex_provider_adapter.py`
- `tests/test_codex_provider_worktree.py`
- `tests/test_codex_provider_process.py`

要求先失败并证明：

1. 只注册 `provider.codex.handoff-v1`；
2. argv 使用固定 Codex 可执行文件和固定 flags，不使用 `shell=True`；
3. 工作目录就是 Session 独占 worktree，不能依赖 `--add-dir` 作为安全边界；
4. 显式 `workspace-write`、`approval_policy=never`、`--ephemeral`、`--json`、禁用 plugins；
5. fake JSONL 解析、turn/usage/事件上限、stdout/stderr 上限；
6. 超时、取消、预算停止终止完整 macOS process group；
7. symlink、路径逃逸、未允许文件、超过 5 文件、过大文件均停止并隔离；
8. 成功和失败均清理 worktree，清理失败阻断后续 Session。

## Task 4：Mac Worker 实现

新增固定 Codex adapter、worktree manager、JSONL parser、process-group runner 和 fake fixture。真实执行只检测既有 Codex CLI/认证，不自动安装或登录。

## Task 5：Windows WPF RED

新增/扩展原生 Windows 测试，先失败并证明：

1. typed client 支持 Provider status、usage confirmation、create/list/get/cancel Session；
2. 云端开发页面显示 Provider ready 状态、固定预算、人工额度确认、启动、取消和安全结果；
3. 不存在 Token/API key、模型、命令、路径或余额数字输入框；
4. 同一 Session 在 ItemsSource 替换、刷新和有界网络错误后仍保持预览；
5. 真实 STA 页面执行 DataBind、Measure、Arrange、UpdateLayout；
6. 按钮 busy/idempotency/终态规则正确。

## Task 6：Windows 实现

在现有 `Picotoo Pet AI.exe` 与“云端开发”页面内增加受控 Provider 面板；复用现有客户端、状态存储、日志脱敏、导航和故障边界。不新增 Helper、WebView、浏览器 UI 或第二程序。

## Task 7：版本与发布合同

一次性把产品、Windows、Mac Core、Mac Worker、Manifest、安装器、报告和测试夹具升级到 `2.3.13.2`，先做仓库级陈旧版本字面量审计，避免分批遗漏。

发布合同必须包含：

- `provider=codex`
- `provider_real_execution_default=false`
- `ci_provider_fixture=fake-jsonl`
- `source_build_on_user_pc=false`
- `source_build_on_user_mac=false`
- 固定预算摘要和禁用自动充值/自动发布声明。

## Task 8：精确头部原生验证与制品

必须在同一精确头部通过：

1. Windows Control Center Slice D CI；
2. Phase 2.3 Slice D Windows Prebuilt Release；
3. Mac Core Slice B CI；
4. Mac Worker Slice D CI。

下载正式制品后独立复核：版本、提交、架构、Manifest、SHA-256、安装/升级/恢复/回滚、WPF 自检、fake Codex 协议、worktree 清理和无用户侧编译。

## Task 9：实机低预算验收

安装正式包后：

1. 用户在 PC 人工查看 Codex Usage；
2. Mac 同一执行用户完成一次 Codex 登录；
3. Windows 为一个全新 approved Handoff 确认一次低预算调用；
4. 真实 Session 完成或按预算安全停止；
5. Return 经本地验证进入 `ready_for_review`；
6. 证明没有自动 commit/push/PR/merge/tag/release，worktree 已清理。

正式包生成不依赖真实额度消耗；真实验收结果必须单独如实记录。