# 茅台身份锁 v2（真实照片提取 · 2026-11-17）

来源：IMG_3576（正脸+花鼻，最高优先级）、IMG_3759–3767（吃饭 9 张）。
原则：可爱化只允许“眼睛略放大、脸更圆、毛更蓬”，下列细节不许改。
**最终母版（主人 2026-11-17 20:39 确认）：17_静态首帧板V2/refs_real/MASTER_body_C8B_v1.png**。不再抽卡改耳朵（C9/C10 为备选，未采用）。

## 一级（错一项 = 废片）
| 部位 | 真实特征 | 常见生成错误 |
|---|---|---|
| 花鼻 | 鼻子中间一条粉色竖带，从上到下，底部分成两瓣粉色；中间一道细暗缝；两个鼻孔周围和鼻子两侧是黑色；边缘不规则 | 全黑鼻、全粉鼻、左右对称图案 |
| 额头 | 头顶到额头整片深黑棕，在两眼之间形成尖角（美人尖），往下变成鼻梁上一条细的深灰线，到鼻子前淡掉 | 额头中间出现白线/白色条纹 |
| 眼周 | 眼睛周围是深色毛，和头顶深色连成一片，向后连到耳根 | 眼周变白；被画成真眼镜（不要写 goggles） |
| 眉斑 | 两块奶白色斜椭圆眉斑，外侧略高，四周被深色毛包围 | 眉斑和白脸连成一片；缺一侧 |
| 脸颊 | 眼睛下方到下颌：奶油色带明显暖金黄色；纯白只在嘴套和下巴 | 整张脸纯白 |
| 眼睛 | 暖棕色、杏仁形、深色眼线、温和 | 蓝眼、死黑眼 |
| 嘴套 | 宽、短、圆 | 长尖嘴（狼/哈士奇） |

## 二级
| 部位 | 真实特征 |
|---|---|
| 耳朵 | 比普通卡通狗小约 1/3，短三角+圆钝耳尖，毛厚，外黑，内侧奶油黄褐色毛（不是粉色皮肤），两耳间距宽、略外张。不能是圆熊耳（C6 实测过头） |
| 被毛 | 超厚长毛，深棕/黑/暖灰棕夹杂的“霜色”，大毛领；不是纯黑 |
| 身体 | 成年大型犬比例，腿粗壮，白胸、白腿、大白爪 |
| 尾巴 | 蓬松，卷在背上 |
| 围巾 | 荧光绿三角棉布，结在颈前，尖角朝下，尖端一个白色小布标（真实存在） |

## 英文身份描述（直接贴进 FLUX 提示词）
An adult wooly long-coat Alaskan Malamute, cute polished 3D family-animation character, adult proportions with sturdy legs, not chibi. Face fur markings: the whole forehead and top of the head are solid dark black-brown fur with no white blaze and no white line; the dark fur forms a widow's peak point between the eyes and narrows into a dark grey line down the bridge of the muzzle that fades out before the nose. The fur around each eye is dark black-brown, forming a dark eye mask of fur that connects to the dark cap and runs back toward the ears. Two separate cream eyebrow spots, each a tilted oval island of cream fur completely surrounded by dark fur. Warm brown almond-shaped eyes, slightly enlarged for cuteness. Below the eyes the cheeks and jaw are cream with a clearly visible warm golden-tan buff tint; pure white only on the muzzle and chin. Two-tone snow nose: a pink vertical band down the center of the nose spreading into two pink lobes at the bottom, with a thin dark crease in the middle; black around both nostrils and on both outer sides; irregular natural edges. Small rounded ears, dark outside, inner ear filled with fluffy cream-tan fur with no pink skin showing, set wide apart and tilted slightly outward. Very thick frosted coat of dark brown, black and warm grey-brown, big fluffy mane, white chest, white legs, big fluffy white paws, fluffy tail curled over the back. Lime-green triangular cotton bandana knotted at the front of the neck, point down, with a small white fabric tag at the tip. No glasses, no eyewear, no cone, no collar, no hat. Not a husky, not a wolf, not a puppy, no long narrow snout.

## 已知提示词陷阱（实测）
- "dark cap" → 画成棒球帽；"saddle" → 画成马鞍；"goggle" → 画成眼镜。只写“fur / 毛色”。
- 低头吃饭镜头嘴最容易变长（C5_eat），需要 LoRA v2 + 侧前方机位来压。

## 剧情固定设定（主人确认）
- 碗里是鸡肉（照真实照片），不用狗粮。
- 全程戴荧光绿三角围巾（含白色小布标）。

## 比例锁（2026-11-17 主人指出“大小比例明显不对”后加入）
- 茅台是大型成年犬：肩高约 75cm、约 45kg、腿长而粗壮。
- 碗约 20cm：碗宽 < 头宽的一半，远低于胸口。
- 机位：狗胸口高度、几米外、长焦感，不用贴地广角（贴地广角会让前景碗变巨大、狗变幼犬）。
- 只有一个碗：写“there is only one bowl in the whole image”，否则比例提示容易让模型画出两个碗。
- 首帧挑选时检查：狗/碗/手 三者相对大小。
- 第二次修正（主人指出：茅台快顶到天花板、手和碗比例不对）：不要写“big relative to the room”；改写具体参照——2.5m 天花板、90cm 台面，茅台坐着头顶约到台面高度；碗写“16–20cm，碗宽≈手长，不比手大”；端碗用双手更自然；50mm 镜头感、手不比碗离镜头更远。
- 第三次修正（主人）：碗应比手掌大约 1.5 倍（≈25cm），不是“碗≈手”；有狗镜头默认全景/中全景（机位 3–4m、高约 1m、35mm），狗只占画面中间一半高度，能看到房间——不要每张都怼近拍。透视下狗离镜头近会显大一点可以接受，但头部不能到吊柜高度。

## 道具实测（主人 2026-11-17）
- 碗：口径约 16cm、底径约 12cm，不锈钢、外壁黑色骨头印花、底部黑橡胶圈；内容为煮熟鸡肉块。比例按此，不再用 25cm。
- 台面高约 1.1m。
