# PicotooPet 2.3.7.1 结果中心实施计划

## 目标

在既有原生 Windows WPF Control Center 中启用“结果”导航，提供只读结果列表、筛选和安全预览。Mac Core 继续作为唯一事实源，Mac Worker 继续只执行显式注册任务，Windows 不保存或推断结果事实。

## 冻结范围

- 用户版本：`2.3.7.1`。
- 结果列表来源：现有 Mac Core 任务快照中 `status=Completed|Archived` 且 `result_id` 非空的任务。
- 排序：`updated_at` 由新到旧。
- 筛选：全部结果、系统诊断、已归档。
- 预览：当前只允许 `system.diagnostic_snapshot`，复用 `/api/v1/tasks/{task_id}/result` 的 64 KiB 固定合同与完整性校验。
- 不显示任意对象路径、原始日志、Token、网络地址、任意 manifest JSON 或文件正文。
- 未知结果类型只能显示元数据和“不支持安全预览”，不能回退到通用 JSON 浏览器。
- 任务中心现有创建、观察、取消、重试和诊断结果卡保持不变。
- 历史 `analysis` 任务保持不支持、不租赁、不修改。

## 合同变化

- Mac Core `ControlCenterCapabilities.result_list=true`。
- Mac Core `ControlCenterCapabilities.result_preview=true`。
- 不新增可写 API；列表复用已同步任务快照，预览复用已有固定诊断结果端点。
- Windows 客户端只有在服务端显式声明上述能力时启用结果导航。

## Windows 页面

- 新增 `ResultsPageViewModel`、`ResultRowViewModel`、`ResultsPage.xaml`。
- 左侧列表显示结果类型、状态、完成时间、任务 ID、结果 ID。
- 右侧显示安全摘要和固定诊断卡片。
- 选择变化时清空旧预览；用户显式点击“加载安全预览”才请求 Mac Core。
- 页面在 Session 快照更新时保留筛选和选中项。
- 真实 STA WPF 测试执行 `Measure`、`Arrange`、`UpdateLayout` 和 DataBind Dispatcher。

## 测试优先任务

1. RED：能力合同要求 `result_list/result_preview=true`，旧实现失败。
2. RED：结果行只接受有结果 ID 的终态任务，按更新时间降序，筛选和选中保持可预测。
3. RED：未知结果类型不可预览；诊断结果可以预览且选择变化清空旧卡片。
4. RED：真实 ResultsPage 在 STA 下完成布局和绑定，不产生写回只读属性异常。
5. GREEN：最小修改 Mac Core 能力、Windows Session 边界、ViewModel、XAML、DataTemplate 和 Shell 路由。
6. 统一版本源升至 `2.3.7.1`，同步安装包、快捷方式、Manifest、报告与验证合同。
7. 运行 Windows Release、Windows Control Center、Mac Core arm64、Mac Worker arm64 四条原生 CI。
8. 仅在精确头部四条 CI 全绿后下载真实制品，独立复算 SHA-256、检查压缩结构并交付用户实机验证。

## 验收

- Windows 标题、左上角和三处受管快捷方式显示 `2.3.7.1`。
- “结果”导航显示“当前能力可用”。
- 页面只列出真实具备结果的终态任务。
- 系统诊断结果可加载固定安全卡片。
- 无结果任务和历史 `analysis` 排队任务不出现在结果列表。
- 未知结果类型不泄露原始内容。
- PR 保持 Draft、open、unmerged；不修改 `main`。
