# 本地 GPU 执行和审片

## 在 Mac 启动

通过 `scripts/mac/INSTALL_MAC.command` 安装 Mac Core，或在功能分支的源代码目录中用 Python 3.12 运行以下命令。沿用现有的设备令牌。源代码启动时可从 Keychain 读取，也可由启动环境提供 `PICOTOO_API_TOKEN`。

```sh
uv sync --no-dev
uv run --no-dev picotoopet-core serve
```

Windows 用同一个 Mac Core 地址和设备令牌连接。Mac 保存任务、审计、质检报告、产物本地路径和 SHA-256。JPEG 缩略图可单独上传，每张最多 300 KiB。原始媒体留在 Windows 项目目录。

## 在 Windows 启动

1. 启动 Claude 维护的文件 worker v2。保留已有生成脚本和目录结构。
2. 使用 Python 3.11 或更新版本，在仓库根目录运行 `py -3 -m pip install -r scripts/windows/requirements-executor.txt`。为生成候选预览、检查视频和执行分轨合成，将本机 `ffmpeg` 和 `ffprobe` 加入 `PATH`。
3. 将 `scripts/windows/executor_bridge.example.toml` 复制为同目录的 `executor_bridge.toml`。填写 Mac Core 根地址、唯一 `worker_id` 和 Windows 现有项目根目录。在启动环境中设置 `PICOTOO_EXECUTOR_TOKEN`。
4. 从带有该环境变量的终端运行 `scripts\windows\RUN_executor_bridge.bat`。按 Ctrl+C 停止。

执行桥每 5 秒轮询空闲队列，运行任务期间每 20 秒续租。待报告进度和回执保存在项目下的 `_queue/executor_bridge/`。同一台机器重启执行桥时继续使用原来的 `worker_id`。如果 Core 已按租约规则将任务转为终态，本地回执仍可在该目录核对。

需要**暂停后续抽卡**而不打断正在运行的文件 Worker 时，可在本机使用
`python scripts/windows/executor_bridge.py scripts/windows/executor_bridge.toml --pause-new`；
用 `--pause-status` 查询，用 `--resume-new` 恢复。只影响当前 Python 执行桥领取新租约，
已提交 GPU 作业不会被强制结束，也不会解除原系统的 GPU HOLD。参见
[Windows 新任务暂停 / Journal 保留](production/WINDOWS_PAUSE_NEW_TASKS.md)。

剧集生成的第一帧和末帧任务使用各自的第一颗 seed。视频使用 YAML 中的候选 seeds；Episode Schema 允许最多 48 颗，但**新建剧集的默认预算限制为每镜 8 颗、每集首次 48 颗**，且按 QC 重抽与 Worker 尝试预估视频秒数。后续阶段优先使用已选的上游图像，否则使用第一张可用图像。拟音跑对应视频候选。执行桥用本机工具 `python -m qc check` 检查图像和视频，每个候选保留完整 JSON 报告、分数、问题和 JPEG。视频另外核对时长和流。需要检查主体数量或身份时，可在生成任务的 `payload.jobs.qc_spec` 中填写 `expect` 和项目内的 `identity_refs`。默认检查器采用本机视觉启发式，模型身份检查使用已有本地权重。复杂动作、穿栏或房间布局仍需导演看图。合成调用 `python -m edit assemble`，按选片、剧集清单和已绑定的本机音轨生成。

## 剧集和审片

```sh
uv run picotoopet episode validate episode.yaml
curl --fail-with-body -H "Authorization: Bearer $PICOTOO_API_TOKEN" \
  -H "Content-Type: application/yaml" --data-binary @episode.yaml \
  "$MAC_CORE_URL/api/v1/episodes"
```

每个分镜按首帧、视频、拟音、质检的顺序执行。桌面「生产」页显示候选和 QC 结果，可记录选用、重做或不要。双击视频候选使用本机播放器打开，或点击「本地播放」。每个分镜都有选用视频后可点击「合成本集」。

### 已有视频和完成回执

在 Windows 的「生产 → 打开本地批次」选择原 worker 归档到 <code>_queue\done</code> 的 <code>*.result.json</code>。工具会从同名归档任务找到 jobs，核对每条视频的镜号、原始 take、seed、字节数和 SHA-256。完整剧本可选。仅有 jobs 时，程序保留原视频提示和镜序，将缺少的导演信息记为「未录入」，采用零偏移硬切和默认 −14 LUFS 的合成设置。

首次填写后用「保存配置…」在本地保存该集的回执、镜号前缀、补拍映射及可选粗剪。下次点击「打开配置…」即可恢复。设备令牌由 Windows 凭据管理器保管。

- **离线审片**可在断网时进行。将 HTML 保存到本机，再双击打开。左右两条可同步播放、切换监听、逐帧观察和记录带时间点的备注。导出的审片 JSON 按候选的来源和文件哈希匹配，建议保存在项目目录。
- **导入到 Mac**使用桌面已有设备鉴权。可附本机 FFprobe 技术报告与 FFmpeg 提取的小 JPEG。Core 原子登记候选，多个设备重试同一批只产生一份记录。带离线决定重导时，仅补入尚未审过的候选，冲突计数显示在「生产」页。历史候选的「重做」记为审片要求，由后续制作任务接手。
- **补拍**可另选 JSON 映射。下例将第二次回执里的源镜号并入已有的 S09。两个批次中的第 1 条各自保留 take、seed 和来源。

```json
[{"receipt":"retake.result.json","shots":{"S09b":"S09"}}]
```

Windows 命令行也可使用。默认只核对本地文件。以下示例在项目根目录运行，脚本路径换为本机代码目录。

```powershell
py -3 C:\Tools\picotoopet\scripts\windows\import_video_candidates.py --project-root . --receipt batch.result.json --episode-id Demo --review-page review.html
py -3 C:\Tools\picotoopet\scripts\windows\import_video_candidates.py --project-root . --receipt batch.result.json --episode-id Demo --decisions Demo_review.json --probe --thumbnails --config C:\Tools\picotoopet\scripts\windows\executor_bridge.toml --apply
```

离线页可带 <code>--cut-plan plan.json --cut-video rough.mp4</code>，从剪辑计划的 <code>shots[].video</code> 项目标记粗剪已使用的片段。该标记独立于人工选用。<code>POST /api/v1/episodes/import</code> 仅登记历史素材，<code>POST /api/v1/episodes</code> 用于启动新剧集生成。拍摄阶段还可在本地把已确定的动作、镜位与主体编译为英文模型提示词。见[离线导演命令](episode-directing.md)。

## 使用假数据验证

```sh
uv run python -m pytest -q tests/integration/test_gpu_executor.py::test_fake_worker_done_after_disconnect
```

该测试启动回环 HTTP 服务，创建 `gen.keyframe` 任务。执行桥领取后，测试用纯色 JPEG 和 `done` 回执模拟文件 worker，再检查任务状态是 `Completed`、产物 SHA-256 匹配且缩略图已经登记。
