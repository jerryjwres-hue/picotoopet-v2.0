# PicotooPet V3.1｜Owner 逐素材使用权声明（不等于生成授权）

## 工作目标

在已有 SHA 锁定 StoryPack + OwnerPrincipal 本机审核基础上，为同一个
StoryPack 中的角色、场景与画风等所有资产增加显式 Owner 使用声明。
不另外建数据库、Worker、审批引擎或安装步骤；直接复用现有 Core 审计链与
idempotency_keys。

## 信任边界

- `storypack.review` 只批准故事画面安排；**不代表**素材商业使用权。
- 新 `asset_use.attest` 仅允许 OwnerPrincipal 对指定 `pet:...` 主体，
  就全部 SHA 锁定资产逐条**声明**：
  - `self_created`：本人独立制作、并确认有商业 AI 动画及分发权利；
  - `commercial_license`：已有允许这些用途的商业许可，声明时指定证据文件 SHA；
  - `written_permission`：已有书面授权，声明时指定证据文件 SHA。
- 文本声明或证据 SHA 本身**不等于已经核实**授权文件的有效性、许可证条款、
  真实版权和肖像许可。正式 MASTER 权利校验仍是独立的生产准入门槛。
- 不导入第三方云服务、不加载视频模型、不开 GPU、不调用 `POST /episodes`。
- Owner Token 必须与设备 Token 不同，且审批只允许 Mac 直接 loopback。
- Owner 凭据源仍采用 Mac 用户私有的 mode 0600 注册表，默认缺失即禁用。

## 调用流程（供后续按钮 UI 复用，不让用户手写 JSON）

1. Owner 在本机安全审核页查看一次性 StoryPack 及全部素材条目。
2. 对每项资产选择来源/权利依据，并确认商业 AI 生成和对外分发两个使用范围。
3. Core `POST /api/v1/studio/storypacks/owner-review/asset-use/preview`
   读取真实受管理的对象字节，核对全部声明的引用 ID、SHA，计算内容绑定的
   `attestation_sha256`。只读，不存储不授权。
4. Owner 确认后，使用唯一 `Idempotency-Key` 调用 `/commit`，
   将明确范围、证据 SHA、过期时间、操作者、凭据版本及主体摘要写入现有不可变审计链。
5. `/verify` 重新验证文件、当前凭据、期限、撤销状态及完全相同的声明，
   `/revoke` 撤销后同一证据不再有效。

## 必须保留的字段

`rights_attested=true` 只表示 Owner 作出明确声明。
返回始终包含：
- `rights_independently_verified=false`
- `master_rights_approved=false`
- `gpu_authorized=false`
- `can_queue=false`

后续正式生产仍须独立校验 MASTER 实体、版权与商业授权文件、
Storyboard 当前审批、Episode 本身 SHA、模型/工作流和 GPU HOLD。

## 本次离线验收

合成 Mac Managed Store 素材、合成 256-bit Owner Token，
测试所有资产一一匹配、SHA 漂移、重复 ID、非法权限、未给出的
第三方证据摘要、幂等重复、撤销、过期记录（在逻辑中）和零任务。
**不接入用户原始茅台 MASTER，不在用户 Mac 生成或修改 Owner 配置文件。**
