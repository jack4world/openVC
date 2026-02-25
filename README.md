<div align="center">
  <h1>🐦 openVC</h1>
  <p><strong>AI-Powered Video Captioning & Translation CLI</strong></p>
  <p><strong>AI 驱动的视频字幕与翻译命令行工具</strong></p>

  <p>
    <a href="#quick-start--快速开始">Quick Start</a> ·
    <a href="#commands--命令">Commands</a> ·
    <a href="#configuration--配置">Configuration</a> ·
    <a href="#features--功能">Features</a>
  </p>
</div>

---

## Overview / 简介

**English** — openVC is a CLI-first pipeline for automated video captioning, bilingual subtitle generation, and semantic video slicing. It uses ASR for transcription, LLM for intelligent sentence splitting and translation, and VAD-based onset snapping to keep subtitles perfectly in sync with speech.

**中文** — openVC 是以命令行为核心的视频字幕自动化流水线，支持语音识别、双语字幕生成和语义片段切割。利用 ASR 转录、LLM 智能断句与翻译，并通过 VAD 语音起始点对齐确保字幕与音频完美同步。

---

## Quick Start / 快速开始

```bash
# Install / 安装
pip install -e .

# Set up LLM API / 配置 LLM API
openvc config set api_key YOUR_KEY
openvc config set base_url https://api.deepseek.com/v1
openvc config set llm_model deepseek-chat

# Process a video with Chinese translation / 处理视频并翻译为中文
openvc process video.mp4 --translate zh

# Process a YouTube URL / 处理 YouTube 链接
openvc process https://youtube.com/watch?v=... --translate zh
```

---

## Commands / 命令

### `openvc process` — Full Pipeline / 完整流水线

```bash
openvc process <video_or_url> [options]

Options:
  --translate LANG        Translate subtitles (zh, en, ja, ko, ...)
                          翻译字幕（目标语言）
  --output DIR            Output directory (default: ./output)
  --no-hitl               Skip all human-in-the-loop checkpoints
                          跳过所有人工审核环节
  --style STYLE           Subtitle style: science-vlog, news, minimal ...
                          字幕样式
  --layout LAYOUT         translate-on-top / original-on-top / only-translate
                          字幕布局
  --sync-check            Enable VAD onset snapping for precise timing
                          开启 VAD 语音起始点对齐
  --quality QUALITY       Video quality: ultra-high / high / medium / low
```

### `openvc slice` — Semantic Clip Extraction / 语义片段切割

```bash
openvc slice <video> --subtitle <ass_or_srt> [options]

Options:
  --topic TEXT     What to extract (e.g. "key insights about AI safety")
                   提取主题（如"关于 AI 安全的核心观点"）
  --count N        Approximate number of clips (default: 5)
                   目标片段数量（默认 5）
  --output-dir DIR Output directory for clips / 片段输出目录
```

### `openvc burn` — Burn Subtitles / 烧录字幕

```bash
openvc burn <video> --subtitle <ass_file> [--output OUT] [--quality QUALITY]
```

### `openvc transcribe` — Transcribe Only / 仅转录

```bash
openvc transcribe <video_or_audio> [--output out.srt]
```

### `openvc subtitle` — Process Existing Subtitle / 处理已有字幕

```bash
openvc subtitle <srt_or_ass> [--translate zh] [--video VIDEO]
```

### `openvc reframe` — Portrait / TikTok Video / 竖屏视频

```bash
openvc reframe <video> [options]

Options:
  --mode MODE         blur-bg (default) / crop-center / split
                      竖屏模式：模糊背景 / 居中裁剪 / 上下分割
  --width W           Output width (default: 1080) / 输出宽度
  --height H          Output height (default: 1920) / 输出高度
  --blur N            Blur strength (default: 40) / 模糊强度
  --subtitle FILE     ASS/SRT to burn into portrait video / 字幕文件
  --style STYLE       Subtitle style preset / 字幕样式
  --layout LAYOUT     translate-on-top / original-on-top / only-translate
```

### `openvc config` — Manage Settings / 配置管理

```bash
openvc config set api_key sk-...
openvc config set llm_model deepseek-chat
openvc config set style science-vlog
openvc config get
```

---

## Features / 功能

### 🎙 Speech Recognition / 语音识别

| Model / 模型 | Language / 语言 | Mode / 模式 | Notes / 说明 |
|---|---|---|---|
| `bijian` (default) | EN / ZH | Online / 在线 | Fast, phrase-level output / 快速，短语级输出 |
| `faster-whisper` | 99 languages | Local / 本地 | Best accuracy, CUDA support / 最高精度，支持 CUDA |
| `whisper-api` | 99 languages | API | OpenAI Whisper API |
| `whisper-cpp` | 99 languages | Local / 本地 | Lightweight local option |

### ✂️ Intelligent Sentence Splitting / 智能断句

- Phrase-level bijian output enables LLM-based natural splitting
- 短语级 bijian 输出配合 LLM 实现自然断句
- Sentences average ~8 words, matching natural speech rhythm
- 每句平均约 8 词，贴合说话节奏
- Feedback loop ensures no segment exceeds word limit
- 反馈循环确保不超出词数限制

### 🌐 Translation / 翻译

- LLM batch translation with retry and missing-segment recovery
- LLM 批量翻译，支持重试和缺失段补全
- Empty string fallback (no English leakage into Chinese output)
- 空字符串兜底（避免英文残留在中文字幕中）
- Permanent error fast-fail (skips retries for 401/auth errors)
- 永久性错误快速失败（401/认证错误不重试）

### 🎯 Subtitle Sync / 字幕同步

- **Global drift correction**: samples 30% of segments, applies median offset
- **全局漂移修正**：采样 30% 的段，应用中位偏移量
- **VAD onset snapping**: per-segment scan to delay subtitles until speech starts
- **VAD 起始点对齐**：逐段扫描，将字幕推迟到语音实际开始时刻

### 📱 TikTok / Reels / Shorts Portrait Video / 竖屏视频生成

Convert any landscape video to 9:16 portrait format with bilingual subtitles — ready to post on TikTok, Instagram Reels, or YouTube Shorts.

将横屏视频一键转换为 9:16 竖屏格式，含双语字幕，直接发布 TikTok、Reels、Shorts。

```bash
# Basic reframe (blur-bg mode, TikTok style) / 基础竖屏转换（模糊背景，TikTok 风格）
openvc reframe video.mp4

# Reframe + burn bilingual subtitles / 竖屏 + 烧录双语字幕
openvc reframe video.mp4 \
  --subtitle video_bilingual.ass \
  --style portrait \
  --layout translate-on-top

# Integrated: full pipeline → translate → reframe → subtitles in one command
# 一体化：完整流水线 → 翻译 → 竖屏 → 字幕，一条命令完成
openvc process video.mp4 --translate zh --reframe
```

**Reframe modes / 竖屏模式：**

| Mode / 模式 | Description / 说明 |
|---|---|
| `blur-bg` (default) | Original video centred on blurred background — TikTok style / 原视频居中 + 模糊背景，TikTok 经典风格 |
| `crop-center` | Centre-crop to 9:16, no letterbox / 居中裁剪为 9:16，无黑边 |
| `split` | Original on top, blurred zoom fill on bottom / 原视频在上，模糊放大填充下半部分 |

- Output resolution: **1080 × 1920** (configurable) / 输出分辨率：1080 × 1920（可调）
- Subtitle position auto-adjusted for portrait canvas / 字幕位置自动适配竖屏画布
- Works with `--slice` to produce portrait short-clips in one pass / 与 `--slice` 配合，一次生成多个竖屏短片

### 🎬 Semantic Video Slicing / 语义片段切割

- LLM analyzes full subtitle to identify topically coherent segments
- LLM 分析完整字幕，识别主题连贯的片段
- Exports each clip with its own time-adjusted subtitle file
- 每个片段导出独立的时间校正字幕文件
- Configurable topic and clip count
- 可配置提取主题和片段数量

### 🎨 Subtitle Styles / 字幕样式

| Style / 样式 | Description / 说明 |
|---|---|
| `science-vlog` | Clean bilingual, bright text with dark outline / 简洁双语，亮色文字深色描边 |
| `news` | Bold, high-contrast / 粗体高对比 |
| `minimal` | Minimal, no outline / 极简无描边 |

---

## Configuration / 配置

All settings persist in `~/.openvc/config.json`.

所有配置持久化保存在 `~/.openvc/config.json`。

```bash
openvc config set api_key       <key>          # LLM API key
openvc config set base_url      <url>          # API endpoint (OpenAI-compatible)
openvc config set llm_model     deepseek-chat  # Model name
openvc config set style         science-vlog   # Default subtitle style
openvc config set layout        translate-on-top
openvc config set sync_check    true           # Always snap subtitles to audio
openvc config set thread_num    8              # Parallel workers
openvc config set batch_size    10             # LLM batch size
```

### Recommended LLM Providers / 推荐 LLM 服务

| Provider | Base URL | Recommended Model |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` |

---

## Installation / 安装

```bash
# Requirements: Python 3.10+, ffmpeg
# 依赖：Python 3.10+，ffmpeg

git clone https://github.com/jack4world/AIRisk-VideoCaptioner.git
cd AIRisk-VideoCaptioner

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install -e .

# Verify / 验证
openvc --help
```

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

---

## Pipeline Architecture / 流水线架构

```
Input (video / URL / audio)
    │
    ▼
[1] Download (yt-dlp)  ──▶  extract audio (.mp3)
    │
    ▼
[2] ASR Transcription  ──▶  phrase-level segments
    │
    ▼
[3] LLM Sentence Split ──▶  natural ~8-word phrases
    │
    ▼
[4] LLM Translation    ──▶  bilingual segments (EN + ZH)
    │
    ▼
[5] VAD Onset Snap     ──▶  time-aligned to actual speech
    │
    ▼
[6] Style & Layout     ──▶  .ass subtitle file
    │
    ▼
[7] Video Synthesis    ──▶  [captioned] output .mp4
    │
    ▼ (optional)
[8] LLM Semantic Slice ──▶  N clips + per-clip subtitles
```

---

## License / 许可证

MIT License — see [LICENSE](./LICENSE)
