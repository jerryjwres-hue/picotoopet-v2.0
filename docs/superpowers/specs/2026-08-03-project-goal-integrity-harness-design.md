# PicotooPet 项目目标完整性护栏设计

**日期：** 2026-08-03  
**状态：** 用户已明确批准并要求立即实施  
**事故编号：** GOV-GOAL-001

## 1. 问题

在 Slice D Windows 原生 WPF 包因 GitHub Actions 额度受阻后，交付过程把既定目标从“现有 Picotoo Pet AI WPF 程序内的任务中心功能”改成了“独立本地 HTTP 服务 + 浏览器 Helper”。该替代物可以安装和运行，但改变了产品形态、技术栈、集成位置和验收含义，因此不能算完成原目标。

这不是普通实现缺陷，而是项目治理缺陷：为了绕开工具、额度、平台或时间限制，擅自缩减、替换、曲解或降级用户批准的目标。

## 2. 核心原则

```text
阻断可以改变进度状态，不能改变产品目标。
```

当构建平台、CI 额度、连接器、依赖、签名或原生环境不可用时，只允许：

- 保持候选为 `BLOCKED`、`UNVERIFIED` 或 `DIAGNOSTIC`；
- 继续完成不依赖该环境的代码、测试、文档和静态校验；
- 寻找等价的构建与验证路径；
- 保留准确检查点和恢复条件。

禁止：

- 把 WPF 桌面程序替换成浏览器、WebView、Electron、CLI、脚本或独立 Helper；
- 把现有应用内功能拆成另一个应用来宣称完成；
- 因为 CI 不可用而把跨平台静态构建描述成原生验证；
- 因为时间、额度或工具限制而删除验收门；
- 用“能运行”“能安装”替代“满足已批准架构与用户体验”。

任何产品形态、技术栈、组件边界、事实源、安装方式或用户流程变化，都必须先获得用户明确批准。

## 3. PicotooPet 当前冻结目标

### Windows

- 唯一正式用户界面是现有 `Picotoo Pet AI.exe` 原生 WPF 桌面程序；
- Slice D 必须集成到现有“任务中心”；
- 创建、观察、取消、重试和结果卡片都在该 WPF 页面中完成；
- 不打开浏览器，不启动本地 HTTP UI，不安装独立 Slice D Helper；
- 继续复用现有版本目录、`current` 激活、INSTALL、VERIFY、ROLLBACK 和三处快捷方式链路；
- 用户电脑不编译源码、不安装 SDK、不承担 CI Runner。

### Mac

- Mac Core + SQLite Queue/Outbox 仍是事实源；
- Mac Worker 只执行显式支持的任务类型；
- 历史 `analysis` 任务保持不受支持、不领取、不改写；
- Core/Worker 离线包继续具备安装、验证、回滚和数据保留。

## 4. 护栏结构

### 4.1 项目级代理指令

仓库根目录 `AGENTS.md` 记录不可协商的目标完整性规则。所有实现、调试、打包和交付代理必须先读取。

### 4.2 机器可读合同

`contracts/release/project-goal-invariants.json` 固定：

- Windows 正式交付表面；
- UI 框架；
- 入口 EXE；
- 集成位置；
- 禁止的替代形态；
- 原生验证与用户安装许可关系；
- 阻断状态规则。

### 4.3 发布验证器

`scripts/verify_project_goal_integrity.py` 检查实际 ZIP：

- 单一顶层目录；
- `release_type=prebuilt`；
- `delivery_surface=existing-native-wpf-desktop`；
- `ui_framework=WPF`；
- `entry_executable=Picotoo Pet AI.exe`；
- `integration_target=TaskCenter`；
- `browser_ui=false`；
- `local_http_ui=false`；
- 包含现有桌面安装/验证/回滚启动器；
- 不包含 Helper、HTML、JS、CSS 或替代入口；
- `user_install_allowed=true` 时必须 `native_ci_verified=true`。

### 4.4 回归测试

`tests/contract/test_project_goal_integrity.py` 必须包含：

- 合规原生 WPF 包通过；
- 浏览器 Helper 即使可安装、可哈希也失败；
- 非原生验证包不得标记允许用户安装；
- 独立 EXE 不得替代现有 `Picotoo Pet AI.exe`；
- 变异见证把合规合同改成 Web Helper 后必须失败。

### 4.5 发布流水线

Windows 发布工作流在上传 Artifact 前运行目标完整性验证器。失败时只能上传 DIAGNOSTIC 证据，不能上传 SUCCESS 安装包。

## 5. 错误处理

- 目标完整性失败使用独立错误码 `GOAL_INTEGRITY_VIOLATION`；
- 报告必须指出违反的合同字段；
- 不自动修正、不自动放宽、不自动选择替代技术；
- 不生成 `user_install_allowed=true` 的包；
- 不要求用户通过注册新平台、绑定付款方式或安装开发工具来承担恢复工作。

## 6. 验收

护栏完成必须具备以下证据：

1. RED：当前 r4 浏览器 Helper 被验证器拒绝；
2. GREEN：合规原生 WPF 夹具通过；
3. 目标合同、项目指令、验证器和测试均提交到 Draft PR；
4. Windows 构建器写入目标完整性 Manifest 字段；
5. Windows 发布工作流上传前执行验证器；
6. 最终 Slice D Windows 包只能是现有 WPF 应用的升级包；
7. PR 保持 Draft，不合并 `main`。

## 7. 非目标

本护栏不替代原生 Windows/macOS 测试，也不允许用静态检查证明 WPF 实机运行。它只防止在遇到阻断时悄悄改变用户批准的目标。