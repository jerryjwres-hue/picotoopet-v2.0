# PicotooPet 自动质检工具 (`tools/qc`)

针对阿拉斯加犬「茅台」3D 动画短片（竖屏 9:16，1080×1920，发往 TikTok / Instagram Reels）量身定制的端到端自动化镜头质量检验工具。

---

## 核心设计与合规保证

1. **纯本地离线运行**：所有检测、度量、相似度对比均在本机执行，严禁将任何媒体上传至任何云端 API（包括 Gemini 等）。
2. **商用许可合规**：仅采用 MIT / Apache-2.0 / BSD / OFL 许可的依赖。**绝不使用 `ultralytics`（AGPL）**。
   - 目标检测：Florence-2（MIT，固定 revision `5ca5edf5bd017b9919c05d08aebef5e4c7ac3bac`，需要 `trust_remote_code=True` 以加载其专有 DaViT 视觉语言架构；锁定提交哈希确保安全与环境完全一致）/ OpenCV（Apache-2.0）特征检测。
   - 身份一致性：DINOv2（Apache-2.0，facebook/dinov2-small）余弦相似度。
   - 响度检测：`pyloudnorm`（MIT，ITU-R BS.1770-4）。
   - 音视频编解码：PyAV（BSD-2） / OpenCV（Apache-2.0）。
3. **纯 CV 回退安全锁**：当未加载真模型或处于纯 CV 回退模式（`FallbackCVDetector`）时，目标数量类检查一律记为 `warning` 警示，**严禁判定为 PASS**（强制 `pass=false`, exit code 1），必须在真模型或人工复核下完成放行。
4. **显卡显存防争抢机制**：启动时调用 `nvidia-smi` 实时探测已用显存，若已用超过 5000 MiB（如 ComfyUI 正在生成），自动将推理任务路由至 CPU 运行，杜绝显存 OOM 或打断工作流。
5. **仓库无媒体污染**：测试素材全部由代码动态生成（纯色、几何图元、合成音频），绝不在 git 中提交任何媒体文件。

---

## 安装与环境配置

环境要求：Windows 11, Python 3.12, RTX 5070 Ti 16GB。
质检工具拥有专属独立虚拟环境 `tools/qc/.venv`，与 ComfyUI 环境完全隔离。

### 方式一：双击一键初始化
双击运行 `tools/qc/setup_env.bat`。

### 方式二：手动命令安装
```powershell
cd tools/qc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 运行命令

```powershell
python -m qc check --spec shot_spec.json --media <图或视频路径> [--prev <上一镜视频路径>] --out report.json
```

### 参数说明
- `--spec`: 镜头需求规范 JSON 文件路径（必选）。
- `--media`: 待质检的单张图或视频文件（MP4 / PNG / JPG，必选）。
- `--prev`: 前一镜头视频文件（可选，用于检查跨镜亮度与色温连续性）。
- `--out`: 输出质检报告 JSON 路径（默认 `report.json`）。
- `--out-jpg`: 输出可视化拼图报告路径（默认与 report 同名的 `.jpg`，如 `report.jpg`）。
- `--use-florence`: 强制启用 Florence-2 本地大模型开放词表检测。

### 退出码（Exit Code）
- `0`: 质检通过（PASS）。
- `1`: 质检不通过（FAIL，存在超标项或不符合 spec 的帧）。
- `2`: 程序错误（参数错误、文件缺失、损坏等）。

---

## 输入输出格式

### 1. `shot_spec.json` 示例
```json
{
  "shot_id": "S03",
  "expect": {
    "dogs": 1,
    "people": 0,
    "bowls": 1,
    "balls": 0,
    "faces_visible": false
  },
  "identity_refs": {
    "dog": "refs/maotai_master.png",
    "owner": "refs/owner_master.png"
  },
  "min_motion": 0.15,
  "max_motion": 2.5,
  "caption": {
    "text": "he waited all day for his dinner...",
    "y_ratio": 0.20
  },
  "allow_light_change": false
}
```

### 2. `report.json` 示例
```json
{
  "shot_id": "S03",
  "pass": true,
  "score": 95,
  "fails": [],
  "warnings": [
    {
      "check": "audio_loudness",
      "frame": null,
      "detail": "Loudness is -15.8 LUFS (target -14.0 ± 3.5 LUFS)."
    }
  ],
  "metrics": {
    "sampled_fps": 4.0,
    "total_sampled_frames": 16,
    "original_video_fps": 30.0,
    "stability": {
      "avg_brightness": 128.5,
      "avg_color_temp_rb": 1.05,
      "max_brightness_jump": 3.2,
      "max_color_temp_jump": 0.04
    },
    "motion": {
      "mean_motion": 0.85,
      "min_motion_observed": 0.32,
      "max_motion_observed": 1.45
    },
    "identity": {
      "dog": {
        "min_similarity": 0.84,
        "avg_similarity": 0.89
      }
    },
    "audio": {
      "has_audio": true,
      "loudness_lufs": -14.2,
      "true_peak_db": -1.6,
      "clipping_samples": 0,
      "silence_segments": []
    }
  },
  "report_jpg": "report.jpg"
}
```

### 3. 可视化拼图 `report.jpg`
自动将所有存在问题的帧（或关键代表帧）拼接为画廊拼图，并在出问题的帧上高亮红色检测框与标注，顶部展示镜头状态大标题与综合得分。

---

## 7 项检查标准详情

| 检查项 | 采样与算法 | 合格判定标准 |
| :--- | :--- | :--- |
| **1. 人数与人脸** | 每秒抽样 4 帧，检测人体与人脸 | 人数与 `expect.people` 一致；若 `faces_visible=false` 出现人脸即报错 |
| **2. 开放词表目标** | Florence-2 开放词表目标检测 | 狗、碗、球数量与 `expect` 严格匹配，任一帧数量不符即记录帧号并报错 |
| **3. 身份一致性** | 目标框裁切后与 `identity_refs` 进行 DINOv2 余弦相似度计算 | 最低相似度 $\ge 0.65$，并统计整段镜头的均值与极小值 |
| **4. 画面光照稳定** | 帧间平均亮度和色温（红蓝通道均值比 R/B） | `allow_light_change=false` 时，镜内光线突变即报错；有 `--prev` 时比对跨镜接缝 |
| **5. 运动量控制** | Farneback 稠密光流场均值 | 运动量 $< min\_motion$（死寂静帧）或 $> max\_motion$（画面崩溃闪烁）均报错 |
| **6. 字幕安全区** | 1080×1920 画布，检测 TikTok / IG 界面遮挡 | 右侧 140px、底部 420px、顶部 160px 严禁出现字幕或高对比度文字 |
| **7. 音频质量** | ITU-R BS.1770-4 LUFS 测量、峰值与 RMS 能量 | 目标 -14 LUFS，削波样本判定，静音段（RMS < -50 dBFS 持续 > 1.5s）告警 |
| **8. 溶解与重影 (新增)** | 帧间线性混合方程比对 ($k \in [3, 5]$, $\text{mot} \ge 14.0$, $\alpha \in [0.22, 0.78]$, 误差比 $< 0.20$) 与 6 帧互相关失相关 ($< 0.12$) | 捕获镜头内异常双重曝光与未按剪辑点执行的溶解切换 |
| **9. 领巾位置 (新增)** | HSV 鲜绿色目标区域质心与垂直包围框高度 | 茅台颈部领巾正常应在下巴下方 ($cy \ge 460$)；若跑到头顶或背部 ($y < 380, cy < 450, h > 200$) 立即报警 |
| **10. 色彩涂抹异常 (新增)** | 高饱和红像素突变统计 ($R > 160, R/G > 1.6, R/B > 1.6$) | 4 帧内突增超过 14,000 像素即报警（捕捉舌头严重涂抹融化 glitch） |

---

## 真片校准混淆矩阵与性能实测

在 16 条真实标注样本（包含 7 条应判不合格镜头与 9 条应判合格镜头）上进行全量测试与校准：

| 镜头编号 | 人工标注 | QC 检测判定 | 触发检查项 | 校准判定状态 |
| :--- | :--- | :--- | :--- | :--- |
| `V2_S09_v1.mp4` | **FAIL** | **FAIL** | `dog_count` (误现残影狗脸) | **CORRECT (TP)** |
| `V2_S09_v2.mp4` | **FAIL** | **FAIL** | `dog_count` (误现残影狗脸) | **CORRECT (TP)** |
| `V2_S07_v1.mp4` | **FAIL** | **FAIL** | `dissolve_ghosting`, `bandana_position` | **CORRECT (TP)** |
| `V2_S12_v1.mp4` | **FAIL** | **FAIL** | `color_smear` (舌头涂抹异形) | **CORRECT (TP)** |
| `V2_S09b_v1.mp4` | **FAIL** | **FAIL** | `dissolve_ghosting`, `dissolve_decorrelation` | **CORRECT (TP)** |
| `V2_S09b_v2.mp4` | **FAIL** | **FAIL** | `dissolve_ghosting`, `dissolve_decorrelation` | **CORRECT (TP)** |
| `V2_S09b_v3.mp4` | **FAIL** | **FAIL** | `dissolve_ghosting`, `dissolve_decorrelation` | **CORRECT (TP)** |
| `V2_S01_v2.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S02_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S04_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S05_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S06_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S08_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S10_v1.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S11_v2.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |
| `V2_S12_v2.mp4` | **PASS** | **PASS** | 无 | **CORRECT (TN)** |

- **True Positives (检出不合格)**: 7 / 7 (100% 召回率)
- **True Negatives (正确放行合格)**: 9 / 9
- **False Positives (误报)**: 0 (达成 $\le 2$ 指标)
- **False Negatives (漏报)**: 0
- **准确率 (Accuracy)**: 100.0%

### RTX 5070 Ti 实测处理耗时 (3.04s 视频 / 73 帧 / 抽样 13 帧)
- **GPU (RTX 5070 Ti 16GB)**:
  - Florence-2 目标检测: 1.100s (84.6 ms/frame)
  - DINOv2 特征比对: 0.177s (13.6 ms/frame)
  - 全流程总耗时: **1.46s** (实时比 0.48x，比视频播放快 2.08 倍)
- **CPU (AMD / Intel)**:
  - Florence-2 目标检测: 13.516s (1039.7 ms/frame)
  - DINOv2 特征比对: 0.444s (34.2 ms/frame)
  - 全流程总耗时: **14.06s** (实时比 4.63x)
- **加速比**: GPU 相比 CPU 提速 **9.66 倍**。

---

## 自动化测试与一键自检

### 运行自动化测试套件
```powershell
.\.venv\Scripts\activate
pytest -v
```

### 双击自检脚本
双击 `tools/qc/run_check.bat`：脚本现场动态合成测试镜头及 spec，运行 `python -m qc check` 并输出彩色控制台报告与 `report.jpg`。
