# PicotooPet V3.1 — Mac 本地 OwnerPrincipal 凭据来源（受控候选）

## 为什么需要

集成候选中的 Owner 审批 API 已经使用独立的主人凭据，但之前 `load_settings()`
没有读取该凭据登记表，导致真实安装的 Mac Core 一直保持 Owner 审批禁用。
本次只补齐来源，不主动创建任何主人身份、令牌、权限或批准。

## 固定位置与权限

- Mac 用户态目录：`~/Library/Application Support/PicotooPetV2/state/owner_review_registry.json`
- **默认无此文件：Owner 审批关闭。** 原有 Mac 安装及升级不产生此文件。
- 只有本机操作员在单独审批/配对流程中才可生成登记文件。
- 登记文件必须属于 Mac Core 运行用户、是普通文件（非符号链接），且只有该用户可读写（`0600`）。
- Core 启动时最多读取 64 KiB，拒绝重复 JSON key、非法字段、权限异常、未授权 scope、损坏内容及不可信文件形态。
- 只存单独 Owner token 的 SHA-256 和权限登记；**不存明文 Owner token，也不复用设备 Bearer。**
- 错误时**拒绝启动而不是静默授予权限**；从备份恢复原登记文件或由操作员撤销该配置后可恢复原默认关闭状态。

## 现有限制（必须保持对用户透明）

1. 这个提交只提供本机安全读取。**尚没有**用户可用的一次性 Owner 令牌生成/二维码配对向导；不允许让用户手写 JSON 或在手机输入源码级配置。
2. 登记表在 Core 启动时载入。修改/删除凭据登记后，**须重启 Core** 才能让新的证书/权限撤销状态生效。分镜审核本身的 `/revoke` 则由现有审计机制即时生效。
3. Owner API 仍限制直连本机 loopback；不能把端口直接转发到互联网，不能凭手机只读会话冒充 Owner。
4. `storypack.review` 仅证明主人审核了精确分镜版本，不代表 MASTER 使用权、版权、GPU HOLD 或真实生产授权。
5. 不提供新的 GPU、Windows Worker 或本地 ComfyUI 执行入口，不能将“Episode 合同有效”提升成“可执行”。

## 内部验收

使用合成 256-bit 随机令牌验证：
- 缺文件时 `OwnerReviewRegistry.credentials == ()`，不创建默认文件
- 真实 Mac `load_settings()` 能从用户私有文件读取受限 actor/scope，审计配置只显示聚合数量
- 设备 token 与 Owner token 不可互换
- 0644/0640、符号链接、重复 JSON key、错误权限、过大文件、非法授权范围必须 fail-closed
- 不触发 GPU、不改已有生产数据库

真实用户部署时仍需先完成操作员发证、首次登录 UI、安全远程通道与跨设备的审计验收。
