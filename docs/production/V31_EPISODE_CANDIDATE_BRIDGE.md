# PicotooPet V3.1：从 StoryPack 到完整 Episode 候选（仍不可执行）

**定位**：解决现有 Episode 草稿缺少具体镜头参数的问题，不新增第二套执行器、数据库或独立安装步骤。

## 数据流

1. 创作台/导演 LLM 一次性生成 StoryPack，经现有 `/studio/storypacks/preview` 校验并取得 `storypack_sha256`。
2. 导演补充每镜的 `emotion`、`camera`、`first_frame`、`video`、`audio`、`transition_out`、可选 `last_frame`/`caption`；整集仅补充 `edit.loudness_lufs`。
3. 通过已有设备 Bearer 的 **只读接口** `POST /api/v1/studio/storypacks/episode-candidate/preview`，一次提交：
   - `storypack`：同一份原始声明
   - `storypack_sha256`：必须精确匹配已冻结 StoryPack
   - `completion`：仅 `edit` 和按原顺序排列的 `shots`，不接受修改镜号/时长/故事动作/画面规格
4. Mac Core 用现有 `Episode` 验证器生成完整、确定性的候选；返回 `candidate_episode_sha256`、`episode`、原故事因果/场景/演员信息与**现有预算只读检查**。
5. 返回中始终标记 `references_trusted=false`、`owner_approved=false`、`can_queue=false`、`can_generate=false`、`can_publish=false`。

**特别说明：** 数据契约有效 `episode_contract_valid=true` ≠ 真实 MASTER 已验证 ≠ 人类审批 ≠ GPU 权限。此接口不能直接提交给当前的设备认证 `POST /episodes`。正式 V3.1 动态故事提交链还需要独立的 Owner / MASTER / GPU 生产准入，严禁让设备 Bearer 单独启动这种动态故事任务。

## 可被 LLM 一次性补充的字段

| 类型 | 必要字段 | 来源/说明 |
|---|---|---|
| StoryPack 固定 | `episode_id`、`title`、`shot_id`、`beat`、`seconds`、`output_profile` | Core 生成，不允许 LLM 覆盖 |
| 单镜导演 | `emotion`、`camera.move/lens/speed` | 现有导演 Skill + 可选 Acting/CineDance 的输出 |
| 首帧 | `first_frame.refs/prompt`、可选 `last_frame` | 暂存未验证引用，必须由可信 MASTER 解析器核验后才使用 |
| 视频 | `video.prompt/negative/seeds` | 现有 Wan/LTX 工作流的生成参数草稿 |
| 音频/剪辑 | `audio.vocal_from/foley`、`transition_out.type/offset_s`、`edit.loudness_lufs` | 明确指定，不从文本剧情猜测 |
| 出品约束 | 现有 Episode Budget | 按原有 GPU/HOLD 规则，只读显示超额原因 |

## 不需要用户额外执行的东西

- 不安装新的导演工具、CLI、视觉模型或云端账号。
- 手机/Windows 的正式创作界面以后只需内部提交这个结构；用户不应手动填写上述 JSON。
- Mac Core 负责只读编译，Windows Worker 继续原有视频和 QC 执行。
- 本 PR 没有改动已有 `POST /episodes`、Owner 认证和工作流授权行为。

## 下一项生产门槛

合并候选后，**受信任的 Core 调用方**必须同时重新验证 StoryPack 与 Episode 摘要、真实文件 SHA、OwnerPrincipal 的当前授权、可撤销 MASTER 使用权、完整动态故事政策及 GPU HOLD。只有验证通过才能让现有 Producer 创建生产任务；本只读接口永远不准直接升级为生产授权。

验收范围：离线三镜头、SHA 漂移、未知字段、重复 seed、机位缺失、画面尺寸不可篡改、预算超标、Bearer 错误以及零 Task/Episode/审批/审计写入。真实模型、用户双机、GPU 与视觉良率：**UNVERIFIED**。
