# PicotooPet V3.1｜Mac → Windows 首帧素材 CPU-only 暂存（安全开发组件）

**目的：**让 Mac 已核对的角色、场景、画风图像以真正的字节和内容哈希
落地到 Windows 现有 Worker 的项目目录，而不是把 Mac 资产 ID
误当作 Windows 路径。不新增 GPU 执行器、数据库、调度器或用户操作界面。

## 复用点

- 输入来自已有 `inspect_frame_sources()` 返回的只读内容绑定清单。
- Mac 使用 `export_frame_bundle(objects_dir, preview, zip_path)`，重新打开
  content-addressed 存储中的真实文件，O_NOFOLLOW + 限大小 + SHA256 读流。
- 生成的 ZIP 固定包含 `manifest.json` 和 `objects/<sha256>`，不得包含任何
  原始绝对路径、Owner Token、Mac sqlite、设备配置、云 API Key。
- Windows 现有 Python Worker 目录旁的 `scripts/windows/stage_frame_bundle.py`
  接受**来自可信 Core Plan 的** `expected_source_bindings_sha256`（不得从 ZIP 本身推导）；
  逐条验证 manifest/schema、严格拒绝路径穿越/多余 ZIP 项/重复条目、
  ZIP 不受限压缩、伪造 SHA、软链接、超大图片和非法文件格式。
- Windows 写入既有 Worker root 下
  `_queue/executor_bridge/staged_references/<sha256>.<png|jpg|webp>`；
  文件名只根据哈希+真实字节格式得出，已有文件必须重新验证 SHA 后才复用。
- 返回的 `worker_ref_paths_by_digest` 格式适用于现有
  `executor_bridge.py::_safe_path(ref, self.board)`，但**尚不自动放入生产
  Plan、Episode 或 Worker 队列**。

## 限制：这不是“一键出片”

1. 现在实现的是可复用的 CPU-only **导出和受控导入组件**。
   它们已由合成图片覆盖，**尚未配置自动跨机器传送**；
   不应要求普通用户搬运 ZIP、复制 SHA 或运行 Python。
2. 下一阶段使用既有 Core/Worker 安全通道，传递此 ZIP 或相同的经过审核的
   字节流，同时将准入绑定到不可修改的 Plan + Owner/MASTER 权利记录。
3. Windows 的文件哈希校验只证明其文件内容与预期来源相同，
   不证明这份 StoryPack 获得商业使用授权、素材属于已批准 MASTER、
   GPU HOLD 已释放，或后续调用能绕过既有默认失败门禁。
4. 即使导入成功，返回字段仍为
   `status=WINDOWS_BYTES_VERIFIED_NO_PRODUCTION_AUTHORITY`、
   `can_queue=false`、`gpu_authorized=false`。
   任何正式 Worker 消费代码都必须**再次核验**文件哈希和冻结的 Plan，
   不能信任旧暂存回执或本地文件名。
5. 目前 Windows Phase 2 预编译 Studio 安装包尚不包含执行此 Python 组件
   所需的完整自动化入口。严禁把离线测试称为成片验收。
6. Mac 第一方源对象默认每件 ≤64MiB、单批合计 ≤128MiB，
   Windows 接受原样 ZIP_STORED、明确 PNG/JPEG/WebP 图片魔数。
   传输协议、重试、自动生命周期管理和正式签名发布尚未完成。

## 原生 CI

- Mac Python：实际构造内容寻址 PNG → 导出 ZIP → Windows 格式导入，
  哈希/绑定/路径对账；更换 Mac 源文件后旧证据必须失效。
- Windows 原生测试：同一合成 ZIP 通过 Windows 文件系统硬链接原子落地；
  重复导入、错哈希、ZIP 多余路径、篡改内容、已有坏文件和软链接必须阻止。
- 完全不连接真实用户设备、不打开视频模型、不发 Comfy POST。
