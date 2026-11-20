# PicotooPet V3.1 — CineDance / Acting / Lira 可选导演适配（离线试点）

> 目的：减少分镜反复解释和跨镜不一致，不增加一套导演、服务、数据库或日常按钮。
> 状态：**源码合同试点**；未安装用户电脑、未调用云端平台、未验证真实 Wan/LTX 画面。

## 1. 来源与边界

- 社区 Skill 指令参考：
  - Acting: https://github.com/RICKY556677/ai-film-skills/tree/main/skills/acting
  - CineDance: https://github.com/RICKY556677/ai-film-skills/tree/main/skills/cinedance-higgsfield
  - Lira: https://github.com/RICKY556677/ai-film-skills/tree/main/skills/lira-image-prompts
- 官方 Higgsfield Skills 是**另一套仓库**：https://github.com/higgsfield-ai/skills 。
- 本试点仅**引用**第三方文档，不复制其源码、Skill 文件或可疑自动安装脚本。社区仓库授权须另行核对，未核对前不得打包再发布第三方文本。
- 这三个方法多以 Seedance / Higgsfield 为写作对象；它们**没有经过** PicotooPet 现有 Wan 2.2 / LTX 2.5 Prompt、ComfyUI 节点或 Windows GPU 的生产兼容性实测。
- 不启用 `higgsfield auth login`、CLI、云端 Generate、模型下载、计费或远端文件上传。

## 2. 零额外操作的放置位置

| 职责 | 已有系统 | Skill 在单次导演创作中的贡献 |
| --- | --- | --- |
| 故事/角色/因果 | StoryPack、现有 director-agent | Acting：动机、障碍、可观察动作、触发和落点 |
| 镜头/空间/连续性 | 现有 ai-storyboard-director + `episode direct` | CineDance：起幅、空间方向、景别、运动、连续性约束 |
| 静态首帧和素材编辑 | MASTER / 现有图像工作流 | Lira：仅资产新建/修改时提供图像建议，不是每镜都触发 |
| 权威生产编译与安全 | Mac Core Episode + OwnerPrincipal + Worker + QC | **完全不替换** |

**一次云端 LLM 导演请求即可覆盖整集。** Mac Core 读一次 StoryPack 的角色、场景、风格引用，按镜号填一份现有 `DirectorDirections` 结构；后续镜头局部修正只改对应方向段落。没有必要在每镜再次加载三份 Skills 或为每个 seed 调用 LLM。

## 3. 唯一的交接格式

目前使用现有 `docs/episode-directing.md` 定义的 `directions.yaml`：

- `identities`：只用 StoryPack 中已声明的角色 ID；其中的形象描述仅为文字，**不是** MASTER 的文件 SHA/使用权授权。
- `shots.<shot_id>.subjects`：只列该镜真的出场的角色；空镜明确为 `[]`。
- `shots.<shot_id>.scene`：依据已声明场景和镜头连续性，描述画面；不得私自扩展新场景。
- `action.trigger/behavior/landing`：Acting 的可观察行为，须与 StoryPack 的 `state_in / action / state_out / because` 一致。
- `camera.opening/trigger/move/landing`：CineDance 的取景、视点和时序。文字镜头运动**不可替代**真实 3D Blockout 或 GPU 动作验证。
- `intent/sound`：可选，导演可读性和少量声响；`sound` 不会自行修改权威 Episode 的 Foley/Audio 配置。
- `Lira` 的静态图片建议不直接写进 `video.prompt`；现有 Episode 的 `first_frame.refs` 必须另经 MASTER 哈希和 Owner 权限审批，不能伪造路径、`@tag` 或认证状态。

**明确禁止**把社区 Skill 文本直接当作可执行 Episode、ComfyUI JSON、模型调用许可证或主人批准凭证。执行权限仍由 Core 的正式门禁决定。

## 4. 实际使用：三镜头茅台演示

项目样本：
- StoryPack：`examples/storypack-maotai-v1.json`
- 导演方向示例：`examples/maotai_optional_film_skills_directions.yaml`
- 现有 Episode 编译：`picotoopet episode direct <episode.yaml> --directions <directions.yaml> --preview`

本示例是**离线模拟**；不包含真实批准的 MASTER 路径或现成的可执行 Episode。必须先通过已有正式编译补齐相机、首帧、音频、视频 Seeds、权限等字段，再才能运行 `episode direct`；不要用本示例跳过生产准入。

`episode direct` 会只替换该镜 `video.prompt`，保留现有首尾帧、`camera`、`audio`、`video.negative` 和 `video.seeds`。这意味着 Skill 提供的 **Prompt 内相机描述** 与最终执行器的独立相机配置仍需校验一致性，不能认为文本已修改真实镜头路径。

## 4.1 修复：分镜因果必须进入真正的视频生成 Prompt

原有 StoryPack `state_in/action/state_out/because/handoff` 已经通过结构校验，
但 **Episode candidate 原先直接信任补全的 `video.prompt`**。生成队列
`ProductionService._shot_jobs` 只把该字段传给 Windows Worker，
不会读取 StoryPack 预览 `shot_context`。因此即使 JSON 分镜正确，
真实生成的视频仍可能完全忽略前后动作与故事目标。

现在 `studio/storypacks/episode-candidate/preview` 在原有同一次编译中：
- 自动把每镜进入状态、可见动作、结束状态、因果理由与 handoff 类型写入
  **实际 `video.prompt`**，然后保留导演补全的视觉指导，整个 Episode SHA 随之改变。
- 首镜或 `continuous` 镜头的 `first_frame.prompt` 会明确描述进入状态；
  如果 `last_frame` 本来存在，其 Prompt 会明确描述结束状态。
- `scene_change` 的首帧不会被强制描绘旧场景；有意切镜和连续承接采用不同提示。
- 不新增用户输入、后台导演流程、模型调用、镜头数量、视频种子、GPU 授权、候选素材或数据库字段。

这是**确保故事约束进入生成器的输入级修复**，不是视频物理连续性保证。
英文导演 Prompt 与原 StoryPack 文本可能混用语言；画面是否遵从动作、
茅台身份/食盆是否一致，仍需用过去失败的粗剪作为对照做真实模型验收。
已有独立 Episode / `episode direct` 的历史输出不被悄悄改写。
无任何 Owner MASTER 审批会因为这一步自动生效。

## 5. 验收与停止条件

**Phase A：离线契约试点**
1. 在 CI 中读取现有三镜头 StoryPack 和方向示例。
2. 校验 ID/出场角色与 StoryPack 一致；通过原生 `load_directions` 与 `direct_episode` 编译。
3. 断言除了每镜 `video.prompt` 外，Seed、首尾帧、音频、真实相机参数、镜序、时长、输出规格全部不变。
4. 不调用 LLM、模型、Comfy API、网络、SQLite 生产队列，GPU HOLD 不变化。

**Phase B：未来获授权后才做真人/真机质量 A/B**
- 相同 3 镜 × 4 秒、832×480、24 fps、相同模型、参考图、Seed、推理参数和镜头选择标准。
- A = 原导演输出；B = 同 StoryPack 的 Acting/CineDance/Lira 适配版本；预先冻结两份 Prompt 的 SHA。
- 统计有效镜头数/首抽接受率、角色漂移、场景空间错误、额外生成次数，以及可核验的 Comfy wall time；缺失 GPU active time 仍标记 UNVERIFIED。
- 如果文字过长、与现有镜头配置矛盾、增加人工纠错、或无可测良率收益，则**撤销适配，不安装新东西**。

## 6. 常驻与移动端原则

- Mac M4 Pro 继续承担一次性导演编译和 StoryPack 验证；Windows 5070 Ti 继续负责现有视频生成和 QC。
- 手机仅复用既有移动 Studio；该试点**不新增**单独界面或手机授权按钮。
- 不引入第二个 Worker、部署脚本、生成 API、调度器或 SQLite 表。
- 阶段门槛：PR #268/#269 的 Owner 审批继续独立开发；第三方 Skill 不得绕过任何 OWNER/GPU/QC 证据。
