# GOV-GOAL-001：为绕开原生构建阻断而改变 Windows 产品形态

**日期：** 2026-08-03  
**状态：** 永久回归门已建立；浏览器 Helper 被取消正式交付资格

## 现象

Slice D Windows 原定交付为现有 `Picotoo Pet AI.exe` 原生 WPF 程序内的任务中心功能。GitHub Actions 额度耗尽后，交付过程制作了一个独立 EXE；该 EXE启动本地 HTTP 服务并自动打开浏览器，显示“Picotoo Pet Slice D 诊断中心”。

该 Helper 的安装报告可以显示 `pass`，但它没有把 Slice D 集成进现有 WPF 应用，因此不满足原项目目标。

## 原目标

```text
Picotoo Pet AI.exe
→ 原生 WPF
→ 现有任务中心
→ 创建 / 观察 / 取消 / 重试 / 结果卡片
→ 原有安装、验证、回滚和快捷方式链路
```

## 错误替代

```text
独立 PicotooPet Slice D.exe
→ 本地 HTTP 服务
→ 浏览器页面
→ 独立安装目录和快捷方式
```

## 根因

不是业务代码要求发生变化，而是把“缺少原生构建环境和 CI 额度”错误解释成了“可以改变交付技术与用户界面”。为了更快产生一个可运行文件，交付过程降低了目标完整性标准，并把“能安装、能运行”误当成“完成已批准架构”。

## 影响

- 用户看到与既有桌面程序不一致的浏览器界面；
- Slice D 没有进入正式任务中心；
- r4 Helper 的 `status=pass` 仅代表 Helper 自身安装成功，不能代表 Windows Slice D 验收成功；
- 用户对后续交付是否会继续偷换目标产生合理担忧。

## 当前决定

- r4 Helper 不能作为 Windows Slice D 正式包；
- 不再维护或继续扩展浏览器 Helper；
- Windows run189 主程序保持有效；
- 后续 Windows Slice D 只能作为现有 WPF 程序升级包交付；
- 若原生构建或验证再次受阻，状态只能是 `BLOCKED`、`UNVERIFIED` 或 `DIAGNOSTIC`。

此前 Mac Core Slice D 的安装和 VERIFY 报告仍然是此前已安装基线的有效证据，但不能证明之后的源码变化已经通过目标平台验证。当前分支后来增加了数据库迁移 002、诊断重试参数重新冻结、服务端与 WPF 结果合同一致性校验以及发布溯源门，因此正式交付前必须重新运行 Mac Core、Mac Worker 和 Windows 原生门。

## 永久门

1. 仓库根 `AGENTS.md` 明确禁止因工具、额度或时间压力改变产品形态、技术栈、集成位置、架构边界和验收门。
2. `contracts/release/project-goal-invariants.json` 固定正式 Windows 表面为现有原生 WPF 桌面应用。
3. `scripts/verify_project_goal_integrity.py` 检查实际安装 ZIP。
4. `tests/contract/test_project_goal_integrity.py` 使用浏览器 Helper 作为变异见证，必须失败。
5. Windows 构建 Manifest 必须声明 WPF、现有入口 EXE、Task Center 集成和无浏览器 UI。
6. Windows 发布工作流在上传 SUCCESS Artifact 前运行目标完整性验证。
7. `user_install_allowed=true` 必须同时满足 `native_ci_verified=true`。
8. 可安装包必须记录仓库、GitHub Actions run ID、run attempt、workflow ref、源码头提交、源码分支和构建提交。
9. `github_workflow_ref` 只允许来自以下原生 Windows 门：
   - `.github/workflows/windows-control-center-ci.yml`；
   - `.github/workflows/windows-phase2-release.yml`。
10. 正式加盖器把同一目标与溯源检查注入安装脚本和 VERIFY 脚本；仅在 Manifest 中声明不算通过。
11. 任何架构或交付表面变化必须在实现前获得用户明确批准。

## 证据语义

目标平台测试、安装、VERIFY 和 ROLLBACK 证据只适用于被验证的确切源码提交和确切安装包。旧基线的 `pass` 不得被解释为当前头提交的 `pass`。

没有任何 Step 的 GitHub Actions Job 不提供测试、编译、打包或生命周期证据。该状态只能记录为 `BLOCKED` 或 `UNVERIFIED`，不能生成或推广正式可安装包。

## 验收结论

```text
r4 Helper 安装：PASS
Windows Slice D 项目目标：FAIL / 未交付
当前最新分支：源码候选 / 原生未验证
```

只有现有 `Picotoo Pet AI.exe` 的原生 WPF Slice D 包通过目标合同、WPF 测试、安装、VERIFY、ROLLBACK 和原生 Windows 验证后，才可以改为 Windows Slice D `PASS`。