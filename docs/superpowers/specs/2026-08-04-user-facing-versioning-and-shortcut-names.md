# PicotooPet 用户可见版本号与快捷方式命名设计

## 状态

- 用户已确认采用方案 A：升级时替换旧快捷方式，只保留当前版本。
- 当前里程碑用户版本：`2.3.6.1`。
- 本设计只修改现有 Mac Core、Mac Worker、Windows WPF 与现有安装/验证/回滚链，不改变产品形态或架构边界。
- PR #8 继续保持 Draft、未合并；不得改动 `main`。

## 目标

建立一个统一、稳定、面向用户的四段式版本号，并确保该版本号在 Windows 页面左上角、窗口标题、桌面快捷方式、开始菜单快捷方式、启动项快捷方式、Mac Core health、Mac Worker 运行时报告、三平台安装包 Manifest 和 VERIFY 报告中一致。

## 版本规则

四段版本格式为：

```text
主阶段.次阶段.功能序号.修订序号
```

当前版本为：

```text
2.3.6.1
```

递增规则：

- 同一功能范围内的缺陷修复：只递增第四段，例如 `2.3.6.2`、`2.3.6.3`。
- 开始下一项正常功能：第三段递增并把第四段重置为 `1`，例如 `2.3.7.1`。
- 第一、第二段仅在项目阶段或兼容性边界发生明确变化时调整，不由构建号自动改变。
- Git SHA、GitHub Actions run ID、run attempt、workflow ref 和包摘要继续保留在 Manifest、报告和 CI 证据中，但不作为主要用户版本号。

## 单一版本源

仓库新增一个唯一、机器可读的产品版本源，值固定为 `2.3.6.1`。Windows、Mac Core、Mac Worker、安装包构建器、安装器、VERIFY、回滚报告和测试都从该版本源读取或在构建时由该版本源生成。

要求：

- 禁止 Windows、Mac Core、Mac Worker 分别维护互不关联的硬编码用户版本。
- CI 必须验证所有正式包声明的用户版本等于统一版本源。
- 构建号和短 SHA 可以追加到内部文件名或溯源字段，但不得覆盖用户版本字段。

## Windows 用户界面

### 左上角

当前副标题改为：

```text
Control Center · v2.3.6.1
```

### 窗口标题

窗口标题改为：

```text
Picotoo Pet AI 2.3.6.1
```

### 页面行为

- 版本文字必须来自编译产物中的统一版本信息，不得在 XAML 中散落硬编码。
- 自测和真实 STA WPF 测试必须验证左上角和窗口标题均显示精确版本。
- 诊断任务、任务中心、现有导航和架构不作功能性变更。

## Windows 快捷方式

桌面、开始菜单和启动项三个快捷方式统一命名为：

```text
Picotoo Pet AI 2.3.6.1
```

文件名为：

```text
Picotoo Pet AI 2.3.6.1.lnk
```

升级行为：

- 删除安装器管理的旧无版本快捷方式 `Picotoo Pet AI.lnk`。
- 删除安装器管理的旧版本快捷方式 `Picotoo Pet AI <四段版本>.lnk`。
- 只创建当前版本 `Picotoo Pet AI 2.3.6.1.lnk`。
- 不删除用户在其他目录手工创建的快捷方式。
- 所有快捷方式继续指向当前激活版本的 `Picotoo Pet AI.exe`。

回滚行为：

- 安装前记录三个位置原有快捷方式的名称、目标、参数、工作目录和图标。
- 回滚时删除当前版本快捷方式并恢复安装前记录的快捷方式。
- 如果升级前是无版本快捷方式，回滚后必须恢复无版本名称。
- 如果升级前是旧版本号快捷方式，回滚后必须恢复原版本号名称。
- 普通桌面和 OneDrive/重定向桌面都必须覆盖。

## Mac Core

- `picotoopet_core.__version__` 由统一版本源生成或读取，当前必须为 `2.3.6.1`。
- `/api/v1/health.version` 必须返回 `2.3.6.1`。
- 安装报告的用户版本字段必须为 `2.3.6.1`，同时保留内部 runtime/build 溯源字段。
- `VERIFY_MAC_CORE_SLICE_B.command` 必须读取当前运行服务的 health 响应并要求 `version == "2.3.6.1"`。
- 仅检查诊断 API 路径存在不足以通过 VERIFY；运行版本不一致必须失败。

## Mac Worker

- Worker 安装和 VERIFY 报告的用户版本字段必须为 `2.3.6.1`。
- Worker 内部包名、运行时角色和支持的任务类型保持不变。
- VERIFY 必须确认当前激活 Worker 对应统一版本，并继续验证 `system.noop` 与 `system.diagnostic_snapshot` 注册。

## 安装包与报告

三个正式包：

1. Mac Core arm64 离线包；
2. Mac Worker arm64 离线包；
3. Windows `win-x64` 自包含 WPF 包。

共同要求：

- Manifest 中增加或规范化 `product_version: "2.3.6.1"`。
- 文件名必须包含 `2.3.6.1`，可在后部保留 run number 和短 SHA 作为内部追溯。
- 安装报告、VERIFY 报告和回滚报告必须包含用户版本字段。
- SHA-256、Manifest 文件路径/大小/哈希、CI provenance 和现有目标合同继续保留。
- 不在用户 Windows 或 Mac 上编译。

## 错误处理

- 统一版本源缺失、格式不是四段数字或任一组件版本不一致时，构建立即失败。
- Windows 安装时，如果无法完整记录旧快捷方式状态，不得切换当前版本指针。
- 新快捷方式创建或验证失败时，安装必须执行现有激活恢复流程。
- Mac VERIFY 发现运行服务版本不一致时，输出明确的 expected/actual，并返回非零状态。
- 版本不一致不能通过修改显示文字来掩盖；运行服务、Manifest 和 UI 必须一致。

## 测试策略

严格采用失败测试先行：

1. 统一版本源格式与值测试。
2. Mac Core `__version__` 和 health 返回 `2.3.6.1` 的失败回归。
3. Mac Core VERIFY 对错误运行版本必须失败。
4. Mac Worker Manifest、安装报告和 VERIFY 版本一致性测试。
5. WPF 左上角与窗口标题真实 STA 渲染测试。
6. Windows 安装后三个位置只存在当前版本快捷方式的生命周期测试。
7. 从无版本快捷方式升级的替换测试。
8. 从旧四段版本快捷方式升级的替换测试。
9. 回滚恢复原快捷方式名称和目标的测试。
10. 普通桌面与 OneDrive/重定向桌面夹具。
11. 三个平台包 Manifest 与统一版本源一致性测试。
12. Windows Release、Windows Control Center、Mac Core arm64、Mac Worker arm64 四条原生 CI 全部通过后才允许发布。

## 验收标准

安装 `2.3.6.1` 后：

- Windows 左上角显示 `Control Center · v2.3.6.1`。
- 窗口标题显示 `Picotoo Pet AI 2.3.6.1`。
- 桌面、开始菜单、启动项各只存在一个 `Picotoo Pet AI 2.3.6.1.lnk`。
- Mac Core health 返回 `2.3.6.1`。
- Mac Core 和 Mac Worker VERIFY 均明确验证并报告 `2.3.6.1`。
- 三个平台安装包和 SHA-256 与精确 PR head 绑定。
- 现有任务中心诊断闭环保持通过。

## 非目标

- 不新增自动更新器。
- 不保留多个历史快捷方式。
- 不改变 Mac Core + SQLite Queue/Outbox 事实源。
- 不改变 Mac Worker 执行边界。
- 不把左侧“诊断”导航改造成日志查询功能。
- 不合并 PR，不修改 `main`。
