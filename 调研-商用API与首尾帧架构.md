# 调研：商用产品/API 能做到什么程度 + “先定首尾再补中间”的可行性

日期：2026-10-29。多数速度数字来自厂商或第三方博客，未经我们实测；带“推算”的是我根据这些数字估的。

## 1. 概念：实时视频生成模型和世界模型

- **世界模型**：根据动作/事件预测下一刻画面，并保持世界状态一致（转身再转回来，东西还在）。
- **实时视频生成模型**：边生成边播放（自回归、按块生成）。
- 现在主流世界模型（Genie、Matrix-Game、LingBot-World、Odyssey）底层几乎都是实时自回归视频模型 + 动作控制 + 记忆。我们用的 LongLive 只有“文字切换”这一种交互，是最简单的一档。

## 2. 面向市场的产品：哪个最接近你的需求、能不能测

| 产品 | 类型 | 能做什么 | 公开的速度/画质 | 能不能拿来测 |
|---|---|---|---|---|
| **Genie 4**（Google DeepMind，2026-10-27 发布） | 世界模型 | 实时生成可交互世界，“可提示的世界事件” | 研究预览 | **测不了**：只开放给受信测试者；Gemini API 只说“早期访问即将开放” |
| Project Genie（底层 Genie 3） | 世界模型应用 | 从文字/图片生成可走动的世界 | 720p、24 FPS（第三方） | 需要 Google AI Ultra 订阅；最初只限美国，据报道在逐步扩到全球（来源互相矛盾） |
| **Decart Lucy 2 / 2.5** | 实时视频编辑（视频进、视频出） | 对一段视频按文字实时修改，“边打字边看到效果” | 厂商称 30 FPS、1080p，延迟低于 100 毫秒 | **能测**：注册送免费额度，有网页演示和 Python/JS SDK |
| **Odyssey-2 / Pro / Max** | 通用世界模型 | 用自然语言实时引导画面继续生成，可用文字或图片起步 | 约 720p、20–22 FPS、约 50 毫秒/帧（第三方） | 有 API 文档（WebRTC）；公开 API 还是内测，来源矛盾，需要去官网确认 |
| Runway GWM-1 | 世界模型 | 实时产品目前主要是数字人（Avatars） | — | 不对口 |
| LTX-2.5（Lightricks，2026-08，**开放权重 + API**） | 快速片段生成（非流式） | 图生视频、**首尾帧补中间** | 10 秒 720p：2×GB200 自部署 6.8 秒，API 23.7 秒（厂商测试） | **能测**：API、LTX Studio 网页、开放权重 |
| Veo 3.1 / Veo 3.1 Fast | 片段生成 | 首尾帧等 | 4–10 秒片段约 45–70 秒 | 能测 |
| Seedance 2.0 | 片段生成 | — | 约 196 秒（LTX 厂商测试） | 能测，但慢 |
| Kling 3.0 Pro | 片段生成 | 首尾帧 | 约 124–398 秒（两个来源差很多） | 能测，但慢 |

图像编辑 API（用来生成“终点图”）：

| 模型 | 平均延迟（第三方博客，量级参考） |
|---|---|
| Nano Banana 2（Gemini） | 约 0.85 秒；另一来源称 1K 分辨率中位数 2–4 秒 |
| Nano Banana Pro | 约 1.8 秒 |
| Seedream 5.0 | 约 2.1 秒 |
| GPT Image 2 | 约 4.2 秒 |

**判断**：
- 商用里**最接近“对着壁纸说一句话，画面实时变过去”的是 Decart Lucy**（实时视频编辑）和 **Odyssey-2**（文字引导的世界模型）。它们是真正的实时，但画质与“照片级、合乎物理”的距离要实测才知道；Decart 的思路本质上和我们的 LongLive + 视频输入一样，只是模型更大、跑在他们的大卡上。
- Genie 4 是天花板，但现在拿不到。
- Seedance、Kling 这类片段模型一段要几分钟，确实不适合；**LTX-2.5 快了一个数量级**，是“首尾帧补中间”能成立的关键。

## 3. “先定首尾再补中间”的可行性推算

### 为什么不会像 Seedance 那样慢

- 终点图用图像模型生成：1–4 秒（API）。
- 中间过程用 LTX-2.5 首尾帧生成：一段 5 秒 720p，API 约 12–24 秒（按 10 秒 23.7 秒线性推算）；如果自己有 H100/GB200 级的卡，几秒到十几秒。
- 对比 Seedance 2.0 一段约 196 秒、Kling 几分钟：**快 8–15 倍**。

### 时间线（用 API，推算）

```
t = 0       用户说“特别大的雨，雾气弥漫”
t ≈ 1 s     提示词层（LLM）把要求整理好
t ≈ 2–5 s   终点图 B 出来（图像模型；雨丝、浓雾、湖面雨点都由模型画）
            ← 画面从这里开始变：A→B 的高清过渡先用本地补帧（RIFE/FILM）慢慢推进
t ≈ 15–30 s LTX-2.5 首尾帧片段（A→B，5 秒）出来
            ← 换成模型生成的真实过渡；或直接生成 B 的“雨一直在下”的动态循环
之后        定住在 B（静止或动态循环）；下一次要求从 B 出发
```

几点说明：
- “开始变化”约 2–5 秒，和现在的 3.5 秒相当；但**画质是终点图的高清画质**，不是 576×320。
- 2–5 秒到 15–30 秒之间那段过渡，先用两张高清图之间的补帧顶上。它是“两张模型生成的图之间的平滑插值”，不是另加的特效；但它本身不是物理过程（更像慢慢溶解）。如果你不能接受，就只能等 15–30 秒的模型过渡片段出来再开始变。
- 如果只用学校的 A40：终点图用 FLUX.2 klein 4B 等本地模型，预计几秒（推算）；但 LTX-2.5 这种大模型在 A40 上生成一段预计要几分钟（推算），过渡/动态部分会明显变慢。

### 可行性结论

- **技术上可行**，而且是目前“丝滑 + 有细节 + 尽快开始变”三者最好的折中。
- 代价：
  1. 需要 API 费用，或更强的显卡。
  2. 过渡的“前十几秒”和“模型过渡片段”之间要衔接好。
  3. 定住后的动态雨景，需要再生成一段循环。
- 风险：
  1. 图像模型改天气时是否保住构图（山不变形），需要实测。
  2. LTX 首尾帧过渡是否自然，要看两张图差异有多大；暴雨这种大改，中间可能出现不合理的形变。

## 4. 建议的测试顺序（你现在就能做，大多在浏览器里）

1. **终点图**：在 Google AI Studio（Nano Banana）上传 Moraine 原图，输入“特别大的雨，雾气弥漫，保持山和湖的构图不变”，看画质、构图保持和耗时。也可以对比 Seedream。
2. **首尾帧过渡**：在 LTX Studio（或 LTX API）用原图做首帧、上一步的图做尾帧，生成 5 秒，看过渡是否丝滑、合乎物理，记录耗时。
3. **商用实时编辑**：Decart 的实时编辑演示（注册有免费额度），输入同样的要求，看实时变化的画质。
4. 如果 1、2 的效果满意，我把这条链路接进网页原型：终点图 → 首尾帧过渡 → 定住 → 接力。需要你自己在终端设置 API 密钥（环境变量），我不会替你填写密钥。

## 来源

- Genie 4 / Project Genie：https://www.datacamp.com/blog/genie-4 、https://www.datastudios.org/post/google-deepmind-genie-4-real-time-world-model-native-audio-research-preview 、https://blog.google/innovation-and-ai/models-and-research/google-deepmind/project-genie/ 、https://en.wikipedia.org/wiki/Project_Genie_(website)
- Decart：https://decart.ai/api-platform 、https://docs.platform.decart.ai/ 、https://fal.ai/explore/decart 、https://aifounderkit.com/ai-tools/decart-real-time-video-generation/
- Odyssey：https://odyssey.ml/introducing-odyssey-2 、https://documentation.api.odyssey.ml 、https://apis.io/providers/odyssey/
- Runway：https://dev.runwayml.com/ 、https://omidsaffari.com/blog/best-real-time-ai-video-generation-apis-2026
- 片段速度对比：https://ltx.io/blog/ai-video-model-speed-comparison 、https://blog.sandbase.ai/ai-video-generation-api-benchmark-veo-3-1-kling-seedance-2026/
- LTX-2.5：https://venturebeat.com/technology/ltx-2-5-can-generate-a-10-second-ai-video-from-an-image-in-just-6-8-seconds-on-nvidia-superchips-and-its-open-weights 、https://ltx.io/model/ltx-2-5 、https://datanorth.ai/news/ltx-releases-ltx-2-5-open-weights-video-world-model 、https://www.runpod.io/blog/ltx-2-5-the-open-weights-world-model-built-for-speed-and-how-to-run-it-on-runpod
- 图像 API 延迟：https://www.atlascloud.ai/blog/guides/2026-ai-image-api-benchmark-gpt-image-2-vs-nano-banana-2-pro-vs-seedream-5-0 、https://zilliz.com/ai-faq/what-are-the-latency-benchmarks-for-nano-banana-2-at-1k-resolution
