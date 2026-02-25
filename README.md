# sky-media-article-creator-skill

一个面向中文公众号/自媒体写作的 Skill。核心目标是：
- 写出“故事 + 观点”风格、可直接发布的纯文本文章；
- 降低文章的模板化和广告感；
- 在需要时自动生成封面图与正文插图，并把素材统一落盘。

## 核心能力

- 文章流程默认采用“两步法”：
  1. 先产出标题候选 + 推荐标题 + 目标读者价值 + 大纲；
  2. 用户确认后再生成全文。
- 仅当用户明确要求“直接一稿”时，才进入快速模式。
- 默认写作风格为“故事 + 观点”，并支持：
  - 感性故事型
  - 干货理性型
  - 职场专业型
  - 轻松吐槽型
- 支持 `soft-intro`（弱宣传）模式：
  - 当用户强调“不像广告/宣传文”时自动启用；
  - 强制提高真实场景与反思占比，压低硬推广表达。
- 字数控制增强：
  - 支持用户自定义区间；
  - 超上限 10% 以上会触发压缩收敛。
- 若用户提供官网/文档链接，会先做“事实抽取”再写，减少杜撰风险。

## 图片能力（本轮重点增强）

脚本 `scripts/generate_article_assets.py` 会解析文章中的 `IMAGE` 标记并生成图片。

本轮已增强：
- 封面文案不照搬完整标题：
  - 会优先压缩为关键词短语（例如 `vibe coding + 工具APP`）。
- 封面与插图都默认强化“核心内容对齐”：
  - 封面：核心文字 + 2–4 个相关图形/物体元素；
  - 插图：只表达对应段落的核心信息。
- 默认视觉风格改为“浓郁色调 + 清晰对比”：
  - 提高饱和度和视觉张力；
  - 避免灰暗、低饱和、发闷的画面。
- 失败重试机制：
  - 生图请求支持自动重试（短退避）；
  - 常见 429 限流场景可自动缓解。
- 文件命名修复：
  - 封面固定 `cover.png`；
  - 正文插图始终从 `inline_1.png` 开始。

## 目录结构

- `SKILL.md`：完整工作流与写作规范（权威说明）
- `scripts/generate_article_assets.py`：图片生成脚本
- `references/personal_tone_examples.md`：个人语气样例
- `agents/openai.yaml`：Agent 元数据

## 快速开始

### 1) 准备文章源文件（含 IMAGE 标记）

示例：

```text
<!-- IMAGE: cover | prompt=中文封面图，主题文字“大号清晰展示：vibe coding + 工具APP”，加入代码窗口、齿轮、PDF图标等元素，不出现人物 | aspect=16:9 -->

这里是正文段落……

<!-- IMAGE: inline | name=开发流程图 | prompt=中文信息插图，展示场景定义、AI生成、人工校准、迭代上线四步流程，不出现人物 | aspect=16:9 -->
```

### 2) 配置环境变量（推荐）

```bash
export IMAGE_API_URL="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
export IMAGE_API_KEY="<your-key>"
# 或使用 ALI_DASHSCOPE_API_KEY
```

### 3) 运行脚本

```bash
python scripts/generate_article_assets.py \
  --article-file /path/to/article.txt \
  --output-dir /path/to/output/folder \
  --cover-aspect 16:9
```

## 输出结果

输出目录默认包含：
- `article_with_images.txt`：正文中 `inline` 标记会被替换为纯文本占位符，例如：
  - `【插图：名称=开发流程图；文件=inline_1.png】`
- `cover.png`：封面图（如果存在封面标记）
- `inline_1.png`, `inline_2.png`, ...：正文插图
- 原始文章副本（便于对照）

## IMAGE 标记规范

- `cover`：封面图
- `inline`：正文插图
- `prompt`：生图提示词（必填）
- `aspect`：图片比例（可选，如 `16:9`, `1:1`）
- `name`：正文插图名称（仅 `inline` 可选）

示例：

```text
<!-- IMAGE: cover | prompt=... | aspect=16:9 -->
<!-- IMAGE: inline | name=对比图 | prompt=... | aspect=16:9 -->
```

## 常见问题

- Q: 为什么图片没生成？
- A: 先检查 `IMAGE_API_URL` 和 `IMAGE_API_KEY` 是否正确，再确认 `prompt` 是否存在。

- Q: 出现 429 限流怎么办？
- A: 脚本已内置重试；若仍失败，建议间隔 20–60 秒后重跑。

- Q: 为什么封面文案不是完整标题？
- A: 这是默认策略，目的是避免封面信息过载，提升可读性和视觉冲击力。

## 使用建议

- 封面文案尽量短：2–8 字或关键词组合（如 `词A + 词B`）。
- 每张插图只表达一个重点，不要把整篇文章内容塞进一张图。
- 文章侧重真实故事、取舍和过程，功能点保持“简洁但有证据”。

