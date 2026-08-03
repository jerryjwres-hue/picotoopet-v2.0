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
- Mac Core 已通过的安装/验证事实保持有效；
- Windows run189 主程序保持有效；
- 后续 Windows Slice D 只能作为现有 WPF 程序升级包交付；
- 若原生构建或验证再次受阻，状态只能是 `BLOCKED`、`UNVERIFIED` 或 `DIAGNOSTIC`。

## 永久门

1. 仓库根 `AGENTS.md` 明确禁止因工具、额度或时间压力改变产品形态、技术栈、集成位置、架构边界和验收门。
2. `contracts/release/project-goal-invariants.json` 固定正式 Windows 表面为现有原生 WPF 桌面应用。
3. `scripts/verify_project_goal_integrity.py` 检查实际安装 ZIP。
4. `tests/contract/test_project_goal_integrity.py` 使用浏览器 Helper 作为变异见证，必须失败。
5. Windows 构建 Manifest 必须声明 WPF、现有入口 EXE、Task Center 集成和无浏览器 UI。
6. Windows 发布工作流在上传 SUCCESS Artifact 前运行目标完整性验证。
7. `user_install_allowed=true` 必须同时满足 `native_ci_verified=true`。
8. 任何架构或交付表面变化必须在实现前获得用户明确批准。

## 验收结论

```text
r4 Helper 安装：PASS
Windows Slice D 项目目标：FAIL / 未交付
```

只有现有 `Picotoo Pet AI.exe` 的原生 WPF Slice D 包通过目标合同、WPF 测试、安装、VERIFY、ROLLBACK 和原生 Windows 验证后，才可以改为 Windows Slice D `PASS`。