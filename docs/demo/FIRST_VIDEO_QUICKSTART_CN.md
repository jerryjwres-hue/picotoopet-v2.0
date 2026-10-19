# PicotooPet 第一条视频 Demo — 直接试用（MVP）

目标：**你明确选中的项目资料 → Mac 本地 AI 脚本 → Windows 本地 ComfyUI 生成真实单镜头 WebM**。这个 Demo 不依赖 Maotai UI 或 Windows 正式 Release ZIP。**它不是**完整多镜头成片，不含已合成的旁白、字幕或正式 Goal Center MP4。

## 需要的环境

- Mac 上已有 Ollama，`gpt-oss:20b` 位于本机 `127.0.0.1:11434`。
- Windows GPU 电脑上的 ComfyUI 正在 `127.0.0.1:8188` 运行，已有 `wan2.2_ti2v_5B_fp16.safetensors`、`umt5_xxl_fp8_e4m3fn_scaled.safetensors`、`wan2.2_vae.safetensors` 和内置 `SaveWEBM` 等节点。
- 两台电脑都有这个仓库和 Python 3.12+。不用先修好 WPF 发布打包。

## 第 1 步：Mac 选定项目资料并生成 AI 脚本

在 Mac 的仓库目录中：

```bash
python3 scripts/demo_video/quick_video.py prepare --facts docs/demo/EXAMPLE_PROJECT_FACTS_CN.md --out video-demo
```

输出 `video-demo/demo-package.json`，包括标题、中文旁白草稿、屏幕文字草稿、英文视觉提示词、固定 49 帧的镜头参数和资料 SHA-256。示例资料可以替换为你自己选定的一份 UTF-8 项目文档；程序**不会扫描别的资料**，不会将文件发送到外部云 API。

将生成的这一个 JSON 文件通过已有的共享目录、U 盘或同步工具复制到 Windows 的 `video-demo/demo-package.json`。这是当前 MVP 的一次显式跨设备交接，后续再连回 Mac Core/Windows UI。

## 第 2 步：Windows 本地 ComfyUI 视频生成

在 Windows 仓库根目录的 PowerShell 中：

```powershell
py -3 scripts/demo_video/quick_video.py render --package video-demo/demo-package.json --out video-demo/rendered
```

成功时产生：

- `video-demo/rendered/first-video.webm`：ComfyUI 本地 GPU 真正输出的约 2 秒静音视频（832×480、24fps、49 帧）。
- `video-demo/rendered/demo-receipt.json`：ComfyUI prompt_id、源项目摘要、文件大小和 SHA-256。

日志应有 `AI_SCRIPT_READY`（Mac）、`COMFY_PROMPT_ID` 和 `FIRST_VIDEO_READY`（Windows）。视频必须可以播放；仅仅看到 GitHub CI 绿色不算真实 GPU 生成成功。

需要延长等待时间：`--timeout-seconds 3600`（最大 7200）。

## 可选：同一台电脑上同时运行 Ollama + ComfyUI

```powershell
py -3 scripts/demo_video/quick_video.py all --facts docs/demo/EXAMPLE_PROJECT_FACTS_CN.md --out video-demo
```

**边界说明：**只能调用固定本机 loopback、冻结 `windows/production/workflows/wan22-ti2v5b-t2v-api-v1.json` 和固定三份模型。不能传任意 workflow JSON、外部 URL 或未知模型。先用一个可播放镜头验证生产通路；后续复用现有 Creative/Production/C009B/C010A/C011 模块，加入自动交接、旁白、拼接、QA 和 Goal Center。
