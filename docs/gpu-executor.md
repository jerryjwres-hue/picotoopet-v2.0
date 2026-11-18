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
2. 使用 Python 3.11 或更新版本，运行 `py -3 -m pip install requests`。若要生成候选预览、检查视频和执行硬切合成，将本机 `ffmpeg` 和 `ffprobe` 加入 `PATH`。
3. 将 `scripts/windows/executor_bridge.example.toml` 复制为同目录的 `executor_bridge.toml`。填写 Mac Core 根地址、唯一 `worker_id` 和 Windows 现有项目根目录。在启动环境中设置 `PICOTOO_EXECUTOR_TOKEN`。
4. 从带有该环境变量的终端运行 `scripts\windows\RUN_executor_bridge.bat`。按 Ctrl+C 停止。

执行桥每 5 秒轮询空闲队列，运行任务期间每 20 秒续租。待报告进度和回执保存在项目下的 `_queue/executor_bridge/`。同一台机器重启执行桥时继续使用原来的 `worker_id`。如果 Core 已按租约规则将任务转为终态，本地回执仍可在该目录核对。

剧集生成的第一帧和末帧任务使用各自的第一颗 seed。视频使用 YAML 中的候选 seeds，每镜最多 48 颗。后续阶段优先使用已选的上游图像，否则使用第一张可用图像。拟音跑对应视频候选。执行桥的质检检查视频尺寸、时长和音轨。当前本地合成器支持无偏移硬切、目标尺寸、帧率和响度，并使用选中视频自带的音轨。其他转场、字幕、配乐和人声／拟音混合由本地剪辑流程处理，任务保留这些参数。

## 剧集和审片

```sh
uv run picotoopet episode validate episode.yaml
curl --fail-with-body -H "Authorization: Bearer $PICOTOO_API_TOKEN" \
  -H "Content-Type: application/yaml" --data-binary @episode.yaml \
  "$MAC_CORE_URL/api/v1/episodes"
```

每个分镜按首帧、视频、拟音、质检的顺序执行。桌面「生产」页显示候选和 QC 结果，可记录选用、重做或不要。双击视频候选使用本机播放器打开，或点击「本地播放」。每个分镜都有选用视频后可点击「合成本集」。

## 使用假数据验证

```sh
uv run python -m pytest -q tests/integration/test_gpu_executor.py::test_fake_worker_done_after_disconnect
```

该测试启动回环 HTTP 服务，创建 `gen.keyframe` 任务。执行桥领取后，测试用纯色 JPEG 和 `done` 回执模拟文件 worker，再检查任务状态是 `Completed`、产物 SHA-256 匹配且缩略图已经登记。
