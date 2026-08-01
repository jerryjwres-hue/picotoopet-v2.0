# Picotoo Pet V2 — Phase 0 验证报告

生成日期：2026-07-30  
冻结基线：V2.2

## 结论

Phase 0 的**源资产封存、哈希登记、V1 冻结、现有业务程序定位、Mac 模型清单登记和 Comfy Desktop 程序路径登记**已完成。所有上传原始文件继续保留在仓库外，V2 不把 V1 作为运行依赖，也没有对 Maotai 正式数据库或其他 Protected 数据执行写入。

## 已验证资产

| 资产 | 实际文件数 | V2 处理方式 |
|---|---:|---|
| Maotai OS 4.1 | 333 | 只读 Connector 来源，禁止直接写正式 SQLite |
| V2.2 最终冻结包 | 3 | 设计与实施约束来源 |
| Windows Workstation V1.1 | 33 | 冻结备份，只参考契约，不继续开发 |
| REAL PET Creator Assistant | 21 | 后续通过 Connector 接入 |
| Review Insight Lab 2.5 | 48 | 历史分析接口参考 |

完整 SHA-256 位于：

- `inventory/source_manifest.json`
- `inventory/source_sha256.txt`

## Mac 模型状态

`gpt-oss:20b` 已由用户截图确认安装，模型 ID 为 `17052f91a42e`。V2 固定其为唯一默认常驻模型。其“实际常驻、自恢复、开机恢复”状态必须在 Mac 上运行 `INSTALL_MAC.command` 和 `VERIFY_MAC.command` 后才可判定通过，当前报告不把“已安装”误写为“已常驻”。

## Windows ComfyUI 状态

已确认程序入口：

```text
C:\zhaoyang lin\opc\Comfy Desktop\Comfy Desktop.exe
```

该路径是桌面程序目录，不直接视为模型、`custom_nodes` 或工作流根目录。交付包中的 Windows 检测器会在实机上读取 AppData、已知 D/E 盘候选和 ComfyUI API，并把 `resources\ComfyUI` 明确标记为只读。

## 未完成但不阻塞代码交付的实机验证

- Windows 实际 ComfyUI 数据目录、API、CUDA/PyTorch 状态。
- 五个主视觉模型在 E 盘的真实下载和哈希验证。
- Mac launchd、Keychain 和 Ollama 常驻恢复。
- 后续 Windows Worker 阶段的 faster-whisper、FFmpeg、RIFE、Real-ESRGAN、SAM2 运行环境。

这些项目不能在当前 Linux 沙箱中伪造为已完成，均由双击安装/验证程序在对应实机生成报告。
