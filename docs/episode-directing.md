# 离线编译分镜视频提示词

先完成对观众注意力、角色行动和摄影机位置的判断。方向表按现有剧集镜号提供取景和动作。命令在本机生成完整的剧集 YAML，只替换所列镜头的 `video.prompt`，保留负向词、seed、镜序、时长、首尾帧、规划镜头字段和声音计划。

```sh
picotoopet episode direct episode.yaml --directions directions.yaml --preview
picotoopet episode direct episode.yaml --directions directions.yaml --output directed.yaml
picotoopet episode validate directed.yaml
```

输出路径应与两个输入文件不同。已有文件内容与结果一致时命令可重复执行，内容不同时保留已有文件。预览向标准输出写入可校验的 YAML。命令本身不读取运行配置，也不启动模型、Mac 服务或生产队列。

## 方向表示例

以下使用虚构角色与布景，镜号须在待编译剧集中存在。

```yaml
identities:
  pup: A cream dog with a dark patch around one eye
shots:
  S01:
    subjects: [pup]
    scene: A red toy ball rolls across a matte blue floor
    intent: Reveal the paw before the curious eyes
    action:
      trigger: The toy rolls into reach
      behavior: The dog shifts weight to one paw and stops the ball with the other
      landing: The ball stops and the dog's ears tip forward
    camera:
      opening: Low close-up showing the ball and both front paws
      trigger: On visible contact with the ball
      move: 缓慢推近
      landing: Keep the planted paws at the bottom of frame as the eyes come into view
    sound: One short thud on contact
  S02:
    subjects: []
    scene: A single metal bowl sits on an empty counter
    action:
      trigger: A warm beam reaches the bowl rim
      behavior: Steam drifts above the rim
      landing: The rim and steam remain clearly visible
    camera:
      opening: Medium view of the counter
      trigger: As the steam becomes visible
      move: 固定机位
      landing: The bowl stays centered in the same frame
```

- `subjects` 每镜明确填写，需要主体时从 `identities` 选取。空镜用 `[]`。
- `action` 描述触发、可见行为和动作结束状态。`camera` 描述起幅、摄影触发和视点落幅。可选 `intent` 指出该镜让观众看懂什么，`sound` 写要听见的少量关键线索。
- 动作、场景、身份、落幅和声音填写英文。可选 `camera.move` 支持英文及少量约定词，包括 `固定`、`缓慢推近`、`拉远`、`跟拍`、`左摇`、`右摇`、`向左平移`、`向右平移`、`移焦`、`变焦拉近`、`变焦拉远`。摄影机推近和镜头变焦分别编译。
- 编译后的提示词由方向表完整给出。原提示词里仍需保留的场景、视觉、动作或声音信息须写入方向表。运行校验后，可根据导演审片要求另行决定是否提交生成。
