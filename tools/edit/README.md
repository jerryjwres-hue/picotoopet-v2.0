# PicotooPet 自动剪辑合成工具 (`tools/edit`)

针对阿拉斯加犬「茅台」3D 动画短片（竖屏 9:16，1080×1920，发往美国 TikTok / Instagram Reels）的多镜头自动剪辑、音频多总线混音、动态视觉特效与成片合成工具。

---

## 核心剪辑与声音工程特性

### 1. 剪辑转场手法与模块化架构
所有转场手法均作为独立函数编写并注册到转场字典中（`@register_transition`），便于无限扩展新手法：
- **硬切 (Hard Cut)**：瞬间镜头切换。
- **J-cut / L-cut**：声音与画面时间错位剪接（声音提前引入 `offset` 秒或画面切换后延续 `offset` 秒）。
- **急摇转场 (Whip Pan)**：支持 `left`、`right`、`up`、`down` 四方向位移，结合物理运动模糊核（中间速度最快处模糊量最大）。
- **匹配剪接 (Match Cut)**：短交叉溶解（$\le 6$ 帧），平滑淡入淡出画面主体。
- **变速曲线 (Speed Curve)**：支持任意关键帧序列（如 `[{"t":0, "x":1.0}, {"t":2.6, "x":0.5}]`），采用连续速度积分映射原始视频对应帧，平滑插值变速。
- **急推镜头 (Punch-In)**：平滑缓动曲线（Cubic Ease-in-out）中心放大裁切与画质重采样。

### 2. 三路专业声音总线与响度母带
- **三路声音总线**：
  1. `Vocal`（狗叫声）：直接取自 LTX 生成视频自带音轨或指定音频。
  2. `Foley & SFX`（动作与环境音效）：脚步声、饭碗碰触声、关门声等。
  3. `Music`（背景配乐）。
- **侧链压制 (Sidechain Ducking)**：背景音乐在狗叫声（Vocal）出现时自动平滑压低指定分贝（如 `-8 dB`），狗叫结束后平滑恢复（40ms Attack, 250ms Release 防抽吸感）。
- **防爆音包络 (Anti-Pop Envelope)**：每个音频切片头尾严格施加 30ms 半余弦淡入淡出，消除数字爆音与接缝咔嗒声。
- **广播级标准化 (Loudnorm & Limiting)**：严格按照 ITU-R BS.1770-4 响度标准归一化至 `-14 LUFS`，真峰值严格限制在 `-1.5 dBTP` 以内，完美适配 TikTok / Reels 算法推荐。

### 3. 字幕系统与安全区自适应
- **样式**：白字加黑色粗描边，任何复杂背景均清晰可见。
- **弹跳出现动画 (Bounce-In Animation)**：文字入场首 0.25 秒施加弹性过冲缓动（Back-out overshoot easing），生动灵巧。
- **安全区防遮挡算法**：画布 1080×1920 上自动探测并避让 TikTok / Instagram 界面遮挡区：
  - 顶部遮挡 160px（搜索栏、状态栏、关注标签）
  - 底部遮挡 420px（账号名、文案、音乐旋转碟片、底栏）
  - 右侧遮挡 140px（头像、点赞、评论、分享按钮）
  - 字幕无论输入何种 `y_ratio`，都会被自动平移夹持进 `[160px, 1500px]` 之间的绝对安全区。

### 4. 工业级交付产物
- **成品视频**：H.264 High Profile, CRF 18, `-preset veryfast`, AAC 192kbps, `+faststart`。
- **时间码剪辑表 `edl.txt`**：标准 SMPTE 时间码表（每镜入出点 `HH:MM:SS:FF`、转场类型及特效备注）。
- **分镜胶卷缩略条 `strip.jpg`**：每镜提取 1 帧中间代表帧，水平拼贴成电影缩略条并印制镜头编号与时间码。

---

## 安装与环境配置

环境要求：Windows 11, Python 3.12, FFmpeg 6.0+（位于系统 PATH）。
拥有专属独立虚拟环境 `tools/edit/.venv`，与 ComfyUI 环境完全隔离。

### 方式一：双击一键初始化
双击运行 `tools/edit/setup_env.bat`。

### 方式二：命令行手动安装
```powershell
cd tools/edit
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 运行命令

```powershell
python -m edit assemble --plan edit_plan.json --out final.mp4
```

### 复刻 cut_v2 制作计划

在 `tools/edit` 下执行以下命令。`--root` 用于计划从另一台机器迁移时替换素材根目录。原计划中有 `root` 时会自动使用 FFmpeg 制作后端。

```powershell
python -m edit assemble --plan cut-plan.json --root .\media --out cut.mp4 --edl cut.tsv
```

单独转换旧计划时，先写入新的 `edit_plan.json`，再用该文件合成。转换器保留镜头顺序和音乐引用的镜头索引，从 FFprobe 读取缺省出点，并写明转场类型、方向、重叠时间、音量和字幕时点。格式标识为 `edit.production.v1`。媒体文件使用相对素材根目录的路径，原计划保留在原处。

```powershell
python -m edit convert --plan cut-plan.json --root .\media --out edit_plan.json
python -m edit assemble --plan edit_plan.json --out cut.mp4 --edl cut.tsv
```

此格式按原剪辑时间线解释 `in`、`out`、数值 `speed`、`punch_in`、字幕和每镜 `audio_offset`，缺省出点从实际媒体读取。原计划中的 `cut` 使用 0.04 秒淡化，`match` 使用 0.16 秒溶解，`whip_left/right/up/down` 使用 0.18 秒位移，`dip` 使用 0.30 秒淡黑。EDL 四列依次为镜号、时间线入点、镜头时长和出镜转场。多段配乐支持按 `shot`（从零开始）加 `offset` 或按 `at` 定位，保留音量、裁切、淡入淡出和侧链压低。计划可用 `font` 引用本地字体，Windows 缺省使用 Arial Bold。

Windows 执行桥把已选视频和已渲染音频绑定到同一后端。Core 的 `cut` 是无重叠硬切。`j_cut` 让下镜声音提前，`l_cut` 延用本镜出点后的可用声音，`speed_ramp` 在镜尾从一倍加速到两倍（默认作用于最后 0.25 秒，窗口可用 `offset_s` 指定）。Foley 生成提示随剧集保留，剪辑接收渲染文件。CLI 复刻和执行桥调用依赖 FFmpeg 与 FFprobe。FFmpeg 需支持 overlay、xfade、sidechaincompress、loudnorm 及 H.264/AAC 编码。可用 drawtext 时沿用原版英文字幕；缺少 drawtext 或字幕含非 ASCII 字符时，Pillow 会检查本地字体的字形并生成透明字幕图层，再按相同时间和位置叠加。系统字体缺字时，设定计划中的 font 为覆盖相应字符的字体文件。

### 参数说明
- `--plan`: 剪辑工程方案 JSON 文件路径（必选）。
- `--out`: 最终合成 MP4 文件输出路径（默认 `final.mp4`）。
- `--edl`: 输出剪辑时间码文本路径（默认 `edl.txt`）。
- `--strip`: 输出代表帧胶卷图路径（默认 `strip.jpg`）。

### 退出码（Exit Code）
- `0`: 剪辑合成成功。
- `1` 或 `2`: 参数错误、源文件缺失或合成异常。

---

## 输入工程文件 `edit_plan.json` 规范

```json
{
  "size": [1080, 1920],
  "fps": 30,
  "loudness_lufs": -14,
  "font": "fonts/Poppins-Bold.ttf",
  "shots": [
    {
      "shot_id": "S01",
      "video": "S01.mp4",
      "in": 0.0,
      "out": 3.2,
      "vocal": {"from": "S01.mp4", "gain_db": 0},
      "foley": {"file": "S01_foley.flac", "gain_db": -3},
      "speed": [{"t": 0, "x": 1.0}, {"t": 2.6, "x": 0.5}],
      "punch_in": {"t": 1.0, "scale": 1.15, "dur": 0.3},
      "transition_out": {"type": "whip", "dur": 0.25, "dir": "left"},
      "caption": {"text": "he waited all day…", "start": 0.3, "end": 2.8, "y_ratio": 0.20}
    },
    {
      "shot_id": "S02",
      "video": "S02.mp4",
      "in": 0.0,
      "out": 4.0,
      "transition_out": {"type": "match", "dur": 0.2},
      "caption": {"text": "finally, feast time!", "start": 0.2, "end": 3.5, "y_ratio": 0.25}
    }
  ],
  "music": {"file": "music.wav", "gain_db": -16, "duck_under_vocal_db": -8},
  "sfx": [{"file": "door_open.wav", "at": 9.4, "gain_db": -2}]
}
```

---

## 自动化测试与一键自检

### 运行自动化测试套件
```powershell
.\.venv\Scripts\activate
pytest -v
```

### 双击自检脚本
双击运行 `tools/edit/run_assemble.bat`：脚本现场动态合成测试镜头视频、音效与测试配乐，执行 `python -m edit assemble`，生成 `final.mp4`、`edl.txt` 与 `strip.jpg`，并打印时间码表。
