# 茅台晚餐 E01 · 交接与下一步（2026-11-17 20:40）

## 已定
- 角色母版：17_静态首帧板V2/refs_real/MASTER_body_C8B_v1.png（身份细节见 MAOTAI_IDENTITY_LOCK_v2.md）
- 碗里放鸡肉；全程戴绿围巾。
- 流程规则：23_流程模板/LOCAL_LTX_PROFILE.md

## 已完成
- 粗剪 v2（旧形象，配音+字幕）：20_粗剪/Maotai_Dinner_E01_roughcut_v2_VO.mp4
- LoRA v1（旧形象 c001，已证明有效但形象已作废）：21_LoRA训练/output/maotai_lora_v1/
- QC v1：19_自动检查QC/
- 形象探索 C2–C10：17_静态首帧板V2/char_v*_out，对比图在 _char_review/

## 下一步（有额度后按顺序做）
1. 用 MASTER_body_C8B_v1 + 身份锁英文描述生成 LoRA 训练集（约 36 张：站/坐/趴/走/低头吃鸡肉/抬头/侧面/正脸，全程戴围巾）
   - 改 jobs_lora_dataset.json 的 refs 和 prompt → RUN_lora_dataset.bat
2. 训练 LoRA v2（复制 21_LoRA训练/maotai_lora_v1.yaml 改名 v2，数据集换新图）→ RUN_train.bat，约 50 分钟
3. 用 LoRA v2 重出 S1–S7 首帧（碗里换鸡肉），人工挑选
4. LTX Desktop 每镜 4 条（关 Auto-enhance，720p 9:16 4s）→ QC v1 → 剪粗剪 v3
## 注意
- 跑 FLUX 前要关掉 LTX Desktop（它占 9.6GB 显存，脚本会拒绝启动）
- 提示词不要写 cap / saddle / goggles（会画成帽子、马鞍、眼镜）
- 低头吃饭镜头嘴容易变长：用侧前方机位 + LoRA v2

## 更新 2026-11-18 00:25（重启后的进度）
- 已定：工作流 V3（Claude Doc“茅台短片·完整制作工作流 V3”），场景＝地下室为主 + 一楼厨房备饭；故事分镜表见 24_场景包/SCENE_NOTES_v1.md。
- 已完成：LoRA v2（C8B_v1 母版，21_LoRA训练/output/maotai_lora_v2）；B1 背景板 PICKS_B1（真实照片风格化）；Polycam 扫描 → B1 平面图 B1_plan_scan_v1.png；主人标注栏杆和水盆（B1_plan_owner_markup.png）。
- 作废：AI 想象的剖面图（比例错）；keyframes v3–v8（比例错误示例）。
- Blender 5.3 通过 winget 安装中，需主人在 Windows 点 UAC“是”；检查 24_场景包/blender_install_log.txt。
- 下一步：Blender 导入 scan GLB（只留 y_min<0.3 的地下室物体）→ 加栏杆/水盆/碗/茅台占位体（肩高 0.7m）→ 渲染真实比例 3/4 剖面图 → 7 个镜头虚拟摄像机出构图+深度图 → 用深度图约束 FLUX 出首帧。
