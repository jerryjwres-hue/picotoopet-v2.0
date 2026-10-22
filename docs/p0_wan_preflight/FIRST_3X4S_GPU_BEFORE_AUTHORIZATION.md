# P0 #91 — Wan 3×4s 首片 GPU 前现场诊断（只读，一页）

**冻结候选**：`19dcf396ba44828641c91c08dc65aa881a41435a`。本页只解释既有 `Test-WanReadOnlyPreflight.ps1`、Worker Journal 和 Comfy GET 的证据；**不是第二个调度器/新 QA/一次 GPU 授权**。用户 Windows PC 与 Comfy GPU 均**未在本次审计中接触**，所有实机状态初始为 `UNVERIFIED`。过去电路/AFCI 异常跳闸，须先经合格电工核实适用供电安全，再由用户单独准许加载模型/渲染；在此之前**不启动/重启 Comfy、WPF GUI、same-EXE Worker**。

## 冻结生产合同，禁止临场改参

| 图/依赖 | 冻结值与源码；本机需证明 |
|---|---|
| T2V API 图 | `windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json`；`comfy.wan22.ti2v5b.t2v.v1`，Comfy **仅 Windows loopback** `http://127.0.0.1:8188` |
| Model ① | `E:\PicotooPet\Models\diffusion_models\wan2.2_ti2v_5B_fp16.safetensors`；SHA256 `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e` |
| Text ② | `E:\PicotooPet\Models\text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors`；SHA256 `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| VAE ③ | `E:\PicotooPet\Models\vae\wan2.2_vae.safetensors`；SHA256 `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156` |
| Comfy nodes | UNETLoader, CLIPLoader (type=wan, device=default), VAELoader, ModelSamplingSD3 (shift=8), CLIPTextEncode×2, Wan22ImageToVideoLatent (batch=1), KSampler (steps=30/cfg=5/uni_pc/simple/denoise=1), VAEDecode, SaveWEBM (VP9/crf=16.111083984375)。**生产 Preflight 还检查 LoadImage**，尽管 T2V 图不使用它。 |
| 时长/分辨率 | 冻结横屏档 832×480，24 fps，**97=4×24+1 frames**，封装名义时长 97/24≈4.042 秒；三条独立 Executable T2V Task，seed/prompt/job/plan digest 从真实 Mac Core 冻结 Plan 读取 |
| WebM/MP4 | SaveWEBM 的 `filename_prefix=PicotooPet/production/{job_id}/{order:000}-{shot_id}`；实际 filename/subfolder 从每条 Comfy history 取得；WebM SHA256 由 executor 核。FFmpeg/ffprobe 和 **libx264** 用于既有 C004/C011 MP4，不能把 VP9 WebM 误报 H.264 MP4。 |

模型三文件按 `windows/bootstrap/model_manifest.json` 固定哈希。整套 bootstrap 清单还有 Wan2.1 VACE + Wan2.1 VAE 两文件，但不是这条 5B T2V 图的必需节点；不应仅因其缺失误判 **T2V** 必然失败。文件在磁盘 ≠ Comfy 载入路径可见：`/object_info` loader choices 还必须显示这些精确文件名。

## RTX 5070 Ti — 源码已知 vs 实机不可推断

- **已知硬件规格**：NVIDIA RTX 5070 Ti 标称 **16 GB GDDR7**（[NVIDIA 官方规格](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/)）；不等于现场驱动当前可用显存。只有已有进程上的 `nvidia-smi` 和 Comfy `/system_stats` 才能确认实机型号/当前内存/设备。二者不能证明最坏峰值。
- **已知内存压力来源**：冻结 FP16 5B diffusion + UMT5 FP8 + Wan2.2 VAE；97 帧的 Wan latent/KSampler、后段 VAEDecode、SaveWEBM VP9 输出。模型权重磁盘大小不可直接相加当 GPU 常驻用量；Comfy 的权重 offload、dtype、PyTorch/CUDA allocator、其他占用会改变峰值。源码没有固定/经实机验证的 5070 Ti **GPU 峰值、GPU active 秒数或足够显存保证**。
- **条件性可行而非 PASS**：[Comfy 官方 Wan2.2 教程](https://docs.comfy.org/tutorials/video/wan/wan2_2) 称 5B 在启用原生 offloading 时可适配约 8 GB VRAM，但不是对 PicotooPet 此冻结图、此 Comfy/驱动版本和 832×480×97 首次任务的承诺。不能先改 832×480、97 帧、VAE decode 或切换量化模型来“测”后宣称合同 PASS。
- **执行前确定性风险**：`SaveWEBM` 缺失、`vp9` 选项缺失、`Wan22ImageToVideoLatent` / `uni_pc` / `simple` / `wan` 枚举不可见，精确文件 SHA 不匹配，ffmpeg `libx264` 不可用，均能无 GPU 判断。**实机才可确认** CUDA/驱动兼容、offloading 实效、峰值/碎片 OOM、实际 VAE 解码、VP9 编码成功、耗时是否超 Worker 的 20 分钟 history 上限、最终成片/画质。

## 三源对账：必须先 HOLD、再 Journal/History/Queue，后讨论 GPU

1. **STOP / 不得打开 GUI 来做检查**。先确认操作员验收 `three-shot-acceptance.json` 为 `mode=hold`、`.armed` 状态及当前 Mac Core Job/Plan Digest；配置**不存在且从未 armed**会回退原无人值守模式。既有 WPF 启动可能同时启动 same-EXE Worker。只允许静态文件读取/现存服务 GET，不触发 `/claim` 或 `/attempt`。
2. **先只读枚举旧 Journal**：`%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\*.submission.json`；逐条检查 `JobId, TaskId, PlanDigest, GraphDigest, Phase, PromptId`。任何 `Prepared/ Submitting/ Submitted/ FailurePending`、损坏 JSON、Job/Digest 冲突或无法核对的旧记录 → `BLOCKED_PENDING_RECONCILIATION`，必须让 G006 原有 recovery owner 处理；**不可清理、改写或直接重新 POST**。旧 `Settled` 仅可作为一个辅助证据，**不能证明其他未记录 POST 不存在**。
3. **再读取已启动 Comfy 的 GET**：`GET /queue`（`queue_running, queue_pending`），`GET /history?max_items=1000` 与每个**Journal/Core 已知 prompt_id** 的 `GET /history/{prompt_id}`；用现有 `ComfyPromptReconciler.FindExactAsync(GraphDigest)` 的规则对照**完整 graph canonical digest**，不能以任务顺序、近似模型名或“最新 ID”猜 prompt。历史可能被裁剪，空队列+空历史**不能消除旧 Journal 中的不确定 POST**。
4. **核对 Core 只读 Job/Plan/Package 与旧请求状态**：Job/Plan Digest 完全一致、3 条恰好 Executable T2V。若存在旧 prompt 仍在 Comfy queue，或 queue 缺证据、历史 `error`、已 completed 却无 WebM、历史缺失、同一 graph 对到两个 prompt、Core pending lease/attempt 未闭合，维持 STOP；**不能以 Core terminal status 代替 CUDA 已停止**。若 Journal 有不确定记录，先按原有 G006 recovery 对账且得到无 pending 的真实证据；不得人工绕开它。
5. **最后运行已经整合的 GET-only PowerShell 5.1 预检**（仅安全供电、已有 Comfy API 活着时）：核验模型完整 SHA、`/object_info` 核心节点+枚举、`/system_stats` / `nvidia-smi` 显存、真实 Comfy data/output root、`ffmpeg -encoders` libx264、`ffprobe`。`-SkipModelHashes` 必定使 model hash 保留 `UNVERIFIED`，**不能作为申请 GPU 授权的完备预检**。既有脚本 `CandidateSha` 字段仍指它最早的源码审计基线，不是当前安装 EXE 的来源证明。

## 现场三态和 STOP 条件

| 分类 | 可以写 PASS 的精确条件 | 否则 |
|---|---|---|
| `PREFLIGHT_PASS_PASSIVE_ONLY` | Windows 现场真实 Comfy GET 全成功；节点/枚举+三模型 exact SHA+loader dropdown 均匹配；output root、FFmpeg/libx264/ffprobe 有实物；设备/VRAM 读取是数值；指定已知 prompt history 的状态和输出可核验 | 模型/节点/编解码器/路径缺失或不匹配 → **BLOCKED**；型号/显存/history 信息不足 → **UNVERIFIED** |
| `OLD_GPU_DRAIN_PASS` | 全量可见 Journal 只读审计，无 pending/身份冲突；已知旧 prompt 与 queue/history/Core 一致且不在运行；不存在未知 POST | 任意旧 Running/Pending、Submitting 无 prompt、history missing、模糊匹配、数据损坏/冲突 → **BLOCKED / STOP** |
| `THREE_SHOT_AUTHORIZATION_ELIGIBLE` | 只有以上两类确证、HOLD-first/job/plan digest 审核通过、实际供电安全获确认之后，才**有资格申请**用户的另行 GPU 授权 | 任一项 BLOCKED/UNVERIFIED → **STOP**；即使全 PASS 也**不是 GPU 成功、模型已加载、或者自动 ALLOW** |
| `LIVE_GPU / THREE_WEBM / MP4_QA` | 首次正式授权之后真实 prompt/history/WebM×3 + SHA、C010A/C011 PASS receipt、人工验片分别独立取证 | 在本轮必须全部 **UNVERIFIED** |

**立刻 STOP**：电路/负载安全未经确认；HOLD 未先于自动 Worker 生效；Comfy queue 非空或无法读取；任何 Journal 未清算、未知 POST、Core/Comfy 身份冲突；模型哈希/loader/node 失败；本地依赖或显存字段未知；预检仅 CI 模拟 PASS；或有人建议在未授权时“先发一个 /prompt 试试看”。**只做交接，不修复 GPU 环境、不发 POST、不改冻结图、不删除 Journal。**
