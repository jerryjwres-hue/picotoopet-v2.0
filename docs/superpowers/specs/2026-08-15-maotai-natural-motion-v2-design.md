# 茅台桌宠 v2：自然动作系统设计

日期：2026-08-15  
状态：设计冻结候选  
目标分支：`feature/interactive-pet-v1-2.3.26.1`  
PR：#35（保持 Draft，实机视觉验收前不合并）

## 1. 目标

把当前“少量整图 + 同图裁切部件 + DispatcherTimer”实现替换为真正连续驱动的 Q 版阿拉斯加「茅台」桌宠系统，使它能自然完成待机、观察、走、跑、跳、坐、趴、睡、伸懒腰、工作敲键盘、疲劳、烦躁、庆祝和用户互动。

验收重点不是“动作数量”，而是：

- 不出现当前同图裁切造成的画面撕裂、重影和接缝。
- 动作之间有起势、重心移动、缓入缓出、落地缓冲和次级跟随，不再瞬间切 Pose。
- 用户输入能即时打断自主动作，结束后平滑回到最新真实业务状态。
- 在 Windows 125% / 150% DPI、窗口缩放和悬浮桌宠模式下保持稳定。
- 桌宠异常不得影响 Shell、Core、Worker、Task、Approval、Queue/Outbox、Result 或 Schema。

## 2. 明确非目标

v2 不引入远程 AI 推理、Provider 调用、WebView/Electron、用户文件扫描、桌宠持久化人格状态，也不让桌宠产生业务写操作。

不再把“生成更多整张 PNG”当作主要动画方案；完整场景图只能作为休息/离线等低交互场景的安全降级，不作为自然运动主路径。

## 3. 根因与架构决策

当前 v1.3 的可见 Rig 把同一张完整 PNG 重复放入 `MaotaiBody / MaotaiHead / MaotaiLeftPawImage / MaotaiRightPawImage / MaotaiTail`，再通过 Clip 裁出局部并独立移动。这个结构天然会暴露重复像素、错误遮挡、边界接缝和部位脱离；220ms 左右的 `DispatcherTimer` 也会让动作呈离散跳变。

v2 冻结以下决策：

**A. 视觉资产改为真正的透明分层 Raster Skeleton。** 每个可动部位必须是独立绘制/导出的透明 PNG，不允许再从同一张完整角色图裁切。关节素材必须带隐藏重叠区，保证旋转时不会露缝。

**B. 主动画改为连续时间骨骼驱动。** 使用 WPF 原生 `Canvas/Image/TransformGroup` 作为显示层，但所有 Pose 由新的连续 Motion Engine 计算，不再用 200~900ms Tick 直接跳位置。

**C. 渲染节拍使用 `CompositionTarget.Rendering`。** 每次显示器渲染回调计算 `deltaTime`，逻辑按时间推进而不是按 Tick 次数推进；显示器 60Hz 时目标为约 60 次姿态更新/秒。

**D. 大动作采用动画图 + 运动学，不采用整图硬切。** 走、跑、跳、落地、坐下、趴下、起身、工作就位均通过骨骼轨迹、解析式两段腿 IK、身体位移和次级弹簧运动组成。少量面部/嘴型可以在同一骨骼 Pose 上做透明帧切换或 CrossFade。

## 4. Raster Skeleton 资产结构

第一版 Rig 使用固定逻辑坐标系和固定 Pivot。所有部件使用透明 PNG，并比可见边缘多保留约 12~24px 的隐藏重叠毛发区域。

核心层：

- `torso_neutral.png`
- `torso_crouch.png`
- `torso_stretch.png`
- `chest_fur.png`
- `head.png`
- `muzzle.png`
- `ear_left.png` / `ear_right.png`
- `eye_left_open.png` / `eye_right_open.png`
- `eye_left_half.png` / `eye_right_half.png`
- `eye_left_closed.png` / `eye_right_closed.png`
- `pupil_left.png` / `pupil_right.png`
- `brow_left.png` / `brow_right.png`
- `mouth_smile.png` / `mouth_tired.png` / `mouth_annoyed.png` / `mouth_yawn.png` / `mouth_tongue.png`
- 左右前腿：upper / lower / paw
- 左右后腿：upper / lower / paw
- 尾巴至少 3 段：base / mid / tip
- 蓝色耳机拆为 headband / left cup / right cup，随头部骨骼运动
- 道具：laptop / keyboard highlight / drink / shadow / effects

所有资产进入固定应用 UI 目录 `%LOCALAPPDATA%\PicotooPet\ui-assets\maotai\v2`；仅白名单文件可加载。打包资源提供低风险 fallback，资产异常只降级桌宠，不中断 Shell。

## 5. 骨骼层级

逻辑树：

`Root -> Body -> Chest -> Head -> Ears/Eyes/Muzzle/Mouth/Headphones`

`Body -> FrontLeftUpper -> FrontLeftLower -> FrontLeftPaw`

`Body -> FrontRightUpper -> FrontRightLower -> FrontRightPaw`

`Body -> HindLeftUpper -> HindLeftLower -> HindLeftPaw`

`Body -> HindRightUpper -> HindRightLower -> HindRightPaw`

`Body -> TailBase -> TailMid -> TailTip`

每个 Bone 只暴露 `Position / Rotation / Scale / Pivot`。渲染器不决定行为；它只接收一帧 `MaotaiPoseFrame`。

## 6. 连续 Motion Engine

新增职责边界：

- `MaotaiMotionEngine`：每帧根据 `deltaTime` 推进当前动画图并输出 Pose。
- `MaotaiAnimationGraph`：定义合法状态和 Transition。
- `MaotaiBehaviorPlanner`：决定下一行为目标，但不直接改图层。
- `MaotaiLocomotionController`：处理水平速度、目标位置、转向、走跑切换和跳跃弧线。
- `MaotaiIkSolver`：解析式两段腿/爪 IK，保证落地时脚掌不滑、工作时爪子落在键盘目标点。
- `MaotaiSpring`：用于头部、耳朵、尾巴、耳机杯等次级跟随和阻尼回弹。
- `MaotaiRasterRenderer`：把 `MaotaiPoseFrame` 应用到 WPF Transform；不含业务逻辑。

每帧禁止扫描目录、重新解码 PNG、创建大量临时对象或访问 Core/Worker。

## 7. 动画图

基础状态：

`Idle -> Look -> Walk -> Run`

`Idle/Walk -> JumpPrep -> JumpAir -> Land -> Idle`

`Idle -> Sit -> LieDown -> Sleep -> Wake -> GetUp -> Idle`

`Idle/Walk -> WorkApproach -> WorkSettle -> WorkTyping`

`WorkTyping -> WorkTired -> Yawn -> WorkTyping`

`WorkTyping -> WorkAnnoyed -> Recover -> WorkTyping`

`AnyInterruptible -> UserReaction -> ResumeLatestBaseState`

所有 Transition 都有明确时长和曲线。禁止从 `Run` 瞬间切 `Sleep`；必须通过停止、减速、坐/趴等合法路径。

## 8. 自然运动规则

### 8.1 走路

步态相位连续推进。左右前后腿使用错相周期；脚掌处于支撑相时锁定地面世界坐标，身体从其上方经过，避免“脚底打滑”。身体有轻微上下起伏和前后倾；头部使用阻尼跟随而不是与身体刚性同步。

### 8.2 跑步

速度超过阈值后平滑从 Walk Blend 到 Run，不瞬切。跑步提高身体前倾、步幅、腾空比例和尾巴跟随幅度。减速时先缩短步幅再回 Idle。

### 8.3 跳跃

`JumpPrep` 先下蹲蓄力；`JumpAir` 使用连续抛物线位置；四肢在起跳后收拢；`Land` 落地瞬间 torso 使用 squash，再由弹簧恢复，耳朵和尾巴延迟回弹。

### 8.4 工作

进入工作前先走到电脑锚点，坐稳后开始 Typing。左右前爪使用 IK 对准两个键盘目标点交替下压；头部大部分时间看屏幕，偶尔看鼠标或左右扫视。疲劳会逐渐降低打字节奏、眼皮下垂、耳朵降低；烦躁则增加打字速度和身体张力，但不改变真实业务 Working 状态。

### 8.5 观察与鼠标互动

瞳孔先跟随，随后头部通过弹簧追踪，耳朵再略晚跟随，形成真实生物的层级反应。鼠标快速跨越角色时不得瞬时“锁头”；设置最大角速度和最大角加速度。

## 9. 行为调度与优先级

优先级从高到低：

1. `Error / Offline` 等真实系统强状态。
2. 用户直接交互：拖动、点击、摸头、击掌、双击。
3. 真实任务驱动：Working / Waiting / Resting。
4. 自主行为：观察、走两步、伸懒腰、坐下、趴下等。

自主行为使用有记忆的加权选择和 Cooldown，同一动作不会连续重复；行为必须有退出条件和最大持续时间。用户交互打断后，动画图负责过渡回最新 `PetPresentation`，不回到过时状态。

## 10. UI 舞台与悬浮桌宠

嵌入侧栏时，茅台在 `PetStage` 内拥有有限地面范围；走跑距离较短，以观察、工作和互动为主。

悬浮桌宠窗口允许更大的水平活动范围：

- 可走到窗口两侧并转向。
- 可跑、跳、坐、趴。
- 拖动时冻结自主 locomotion，释放后执行短落地/站稳过渡。
- 边缘吸附保留，但吸附完成后角色先稳定 Pose，再恢复自主行为。

窗口位置移动和角色内部骨骼运动分离，避免两套 Transform 相互叠加造成抖动。

## 11. 性能与稳定性

- 只在 `Loaded && IsVisible` 时订阅 `CompositionTarget.Rendering`；隐藏或卸载立即退订。
- `deltaTime` 做上限裁剪，窗口卡顿后不会一次跳过巨大距离。
- 图片启动时一次加载、Freeze 和缓存；每帧仅更新 Transform/Opacity。
- 目标：常规桌宠更新不制造持续 Gen0 垃圾；不允许每帧 LINQ、字符串格式化或集合分配。
- 支持 125% / 150% DPI；使用逻辑坐标、`UseLayoutRounding`、`SnapsToDevicePixels`，素材始终按统一逻辑尺寸布局。
- 任何资产解码失败 -> 透明/安全 fallback + 保留状态文字，不允许异常穿透到 Shell。

## 12. 测试策略

新增 v2 Smoke/Unit Contract：

- Renderer 中不存在“同一完整 Source + Clip 裁头/爪/尾”的主路径。
- Motion Engine 使用时间推进，可在固定 `deltaTime` 下确定性测试。
- `Walk -> Run`、`JumpPrep -> JumpAir -> Land`、`WorkApproach -> WorkTyping` 过渡合法。
- 两段 IK 在可达目标内误差受限；不可达目标被正确 clamp。
- Spring 在指定时间内收敛且无数值爆炸。
- 用户交互优先级高于自主动作；解除交互后回最新 Base State。
- hidden/unloaded 时无 Render subscription。
- 公开桌宠 API 不出现 `Approve / Reject / CreateTask / CancelTask / Save / Connect` 等业务写入方法。
- v1.2/v1.3 业务状态映射和 Simple Mode 五项导航契约继续通过。

CI 必须继续通过：contract/security、legacy regression、WPF Smoke、warnings-as-errors build、published self-test、Windows Prebuilt Release、installer lifecycle。

## 13. 实施分期

### Phase A — 引擎骨架

先建立 Motion Engine、Animation Graph、IK、Spring 和 Renderer 接口，并用测试用程序姿态验证 60Hz 连续运动，不依赖最终美术。

### Phase B — 茅台 v2 真分层资产

制作并校验专用透明部件、Pivot 和 z-order；彻底移除可见路径中的同图裁切 Rig。

### Phase C — 自然动作

依次完成 Idle/Look、Walk、Run、Jump/Land、Sit/Lie/Sleep、WorkApproach/Typing、Tired/Annoyed，再接点击/摸头/拖动/庆祝。

### Phase D — 悬浮桌宠与实机调参

扩大 locomotion 范围，校正 DPI、拖动、吸附和动画衔接；以真实 Windows 机器进行视觉验收。

## 14. 完成标准

v2 只有在以下条件同时满足时才算完成：

- 视觉上无同图裁切撕裂。
- 走、跑、跳、落地、坐、趴、工作至少一整套动作在实机连续播放无明显硬切。
- 鼠标观察、摸头、点击、拖动可以自然插入并平滑恢复。
- 真实工作/等待/离线状态仍由现有 `PetPresentation` 决定。
- Windows 主 CI 与正式 Prebuilt Release 全绿。
- 用户在真实 Windows 上接受角色观感和动作连贯性。

在最后一项完成前，PR #35 保持 Draft、未合并。