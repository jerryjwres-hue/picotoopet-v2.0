# PicotooPet 2.3.26.1 Operator Home Reference UI Design

## 目标

把用户确认的第二张参考图冻结为 Windows Simple Mode 首页的像素级实现基准。实现必须是真实 WPF 控件、真实状态绑定和正式资源，不允许把整张截图当静态背景冒充界面。

## 视觉基准

- 左侧深蓝侧栏宽度、顶部品牌区、五个主导航、设置入口、AI 助手状态区和用户卡按参考图的层级、密度和比例实现。
- 主区顶部采用参考图同等密度的标题/状态条；Hero 新建任务卡、右侧系统状态卡、三张任务摘要卡、资源监控、最近任务、系统日志、工作组件区按参考图的二维结构实现。
- 卡片统一使用轻边框、浅阴影、12–18px 级圆角、蓝/橙/绿语义色和紧凑但舒适的间距。
- 不保留当前版本的大面积空白卡和工程原型视觉。
- 首页之外的待审核、进行中、已完成、新建任务、高级及高级子页继续继承相同主题，不回退到默认 WPF 视觉。

## 阿拉斯加视觉资源

- Hero 和左侧助手使用参考图中同类的高质量阿拉斯加犬视觉，不再使用当前纯矢量卡通狗。
- 三种状态都有独立视觉：工作=耳机/电脑；休息=泡澡/玩耍；掉线=睡眠。
- 资源作为 WPF Resource 随程序打包，加载失败必须有无崩溃回退。

## 助手状态语义

状态只来自既有 Core/Worker/任务事实，不创建第二状态源。

1. Core 或 Worker 不在线：`OfflineSleeping`，灰色状态灯，睡眠图。
2. Core/Worker 在线且 Worker 明确报告 `executing`：`Working`，绿色状态灯，工作图。
3. Core/Worker 在线但 Worker 未报告 `executing`：`Resting`，琥珀/橙色状态灯，休息图。
4. `Queued` / 等待执行任务不得触发 Working。
5. UI 中所有助手状态灯、标题、图片和辅助文案必须来自同一状态键，禁止出现“休息中却绿灯”或不同区域状态互相矛盾。

## 真实性约束

- 没有真实 CPU/内存/磁盘遥测时，不显示伪造百分比；显示“未接入”。
- 没有真实任务进度时，不伪造 68% 等百分比。
- Search 在有界外部采集能力正式接入前继续显示“尚未接入”。
- Paid-AI 默认关闭、schema 18、Promotion governance-only、Windows 无 Provider secrets 等既有安全边界不变。

## 响应式与兼容

- 参考基准优先针对约 1366×853 / 1448×1086 这类桌面窗口密度收敛。
- 仍支持既有 MinWidth/MinHeight 和垂直滚动，避免 125%/150% DPI 下控件裁切。
- 不改变 Mac Core / Mac Worker durable facts 或 API schema。

## 验收

- 视觉：与确认的参考图在布局、信息密度、主要尺寸关系、配色和阿拉斯加视觉上达到肉眼接近 1:1，而不是仅“同风格”。
- 逻辑：空闲连接时助手必须显示休息+琥珀灯；真实 executing 才工作+绿灯；掉线睡眠+灰灯。
- 回归：Windows WPF STA smoke、warnings-as-errors build、published self-test、installer lifecycle 和既有 contract/security tests 全部通过。
