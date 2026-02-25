# VideoCaptioner — Deep Research Report

## Overview

VideoCaptioner (卡卡字幕助手) is a desktop GUI application for automating the full video captioning workflow. It is authored by Weifeng, version v1.4.0, built with Python + PyQt5. The app supports: extracting audio from video, transcribing speech to word-level timestamped subtitles, splitting/segmenting subtitles with LLM assistance, optimizing subtitle quality via LLM, translating subtitles (LLM or free APIs), and re-embedding subtitles back into video with FFmpeg.

---

## Technology Stack

| Layer | Technology |
|---|---|
| UI Framework | PyQt5 + PyQt-Fluent-Widgets |
| Config Persistence | `qfluentwidgets.QConfig` → `AppData/settings.json` |
| ASR | Bilibili Bcut API, JianYing (CapCut/ByteDance) API, Whisper API, FasterWhisper (local), WhisperCpp (local) |
| LLM | OpenAI-compatible API (OpenAI, SiliconCloud, DeepSeek, Ollama, LM Studio, Gemini, ChatGLM) |
| Translation | LLM (via OpenAI API), Bing, Google, DeepLX |
| TTS | OpenAI TTS, OpenAI FM, SiliconFlow TTS |
| Video Processing | FFmpeg (subprocess) |
| Caching | `diskcache` — separate caches for ASR, LLM calls, translation, TTS |
| Retry | `tenacity` — exponential backoff on RateLimitError |
| Audio | `pydub` — chunking, duration detection |
| Dependency Packages | `requests`, `openai`, `json-repair`, `langdetect`, `yt-dlp`, `modelscope`, `psutil`, `GPUtil` |

---

## Project Structure

```
VideoCaptioner/
├── main.py                     # Entry point — bootstraps Qt, i18n, MainWindow
├── requirements.txt
├── pytest.ini
├── run.sh / run.bat            # Launch scripts (venv setup + python main.py)
├── app/
│   ├── config.py               # Global path constants: ROOT, APPDATA, RESOURCE, WORK, BIN
│   ├── __init__.py
│   ├── common/
│   │   ├── config.py           # QConfig subclass (all settings), cfg singleton
│   │   └── signal_bus.py       # Global Qt signal bus
│   ├── components/             # Reusable UI dialog/widget components
│   ├── view/                   # Full PyQt5 view pages
│   ├── thread/                 # QThread subclasses (one per major operation)
│   └── core/
│       ├── entities.py         # All dataclass/enum domain models
│       ├── task_factory.py     # TaskFactory: creates Task objects from cfg singleton
│       ├── constant.py         # UI constants (InfoBar durations, etc.)
│       ├── asr/                # Speech recognition implementations
│       ├── split/              # Subtitle segmentation logic
│       ├── optimize/           # Subtitle optimization via LLM
│       ├── translate/          # Translation backends
│       ├── tts/                # Text-to-speech backends
│       ├── llm/                # LLM client, prompts interface, utilities
│       ├── utils/              # Shared utilities (cache, logger, video, text, etc.)
│       └── prompts/            # Prompt .md files loaded at runtime
├── resource/
│   ├── assets/                 # Images, icons, QSS stylesheets
│   ├── bin/                    # External binaries (Faster-Whisper-XXL, VLC, FFmpeg)
│   ├── subtitle_style/         # ASS subtitle style presets (.txt files)
│   └── translations/           # Qt i18n files (.ts + .qm) for ZH/EN/HK
├── AppData/
│   ├── settings.json           # Persisted user config
│   ├── logs/app.log
│   └── cache/                  # diskcache directories (asr_results, llm_translation, etc.)
├── work-dir/                   # Default working directory for output files
├── tests/                      # pytest test suite
└── docs/                       # VitePress documentation site
```

---

## Entry Point Flow (`main.py`)

1. Sets `QT_QPA_PLATFORM_PLUGIN_PATH` for PyQt5 plugins.
2. Loads `cfg` singleton (reads `AppData/settings.json`).
3. Applies cache enable/disable per `cfg.cache_enabled`.
4. Configures DPI scaling.
5. Sets up Qt internationalization via `.qm` files.
6. Instantiates `MainWindow` and starts the event loop.

---

## Core Domain Models (`app/core/entities.py`)

All domain types are defined here:

- **`ASRDataSeg`** (in `asr_data.py`): One time-stamped subtitle segment — `text`, `translated_text`, `start_time` (ms), `end_time` (ms).
- **`ASRData`**: Ordered list of `ASRDataSeg`. Can serialize to/from SRT, ASS, VTT, JSON, TXT. Has methods: `is_word_timestamp()`, `split_to_word_segments()`, `optimize_timing()`, `merge_segments()`, etc.
- **`TranscribeConfig`**: All params for a transcription job (model type, language, word timestamps, Whisper variants).
- **`SubtitleConfig`**: All params for subtitle processing (LLM API keys, translate/optimize flags, batch size, thread count, layout, style).
- **`SynthesisConfig`**: Video output params (quality CRF/preset, soft vs hard subtitle).
- **Task types**: `TranscribeTask`, `SubtitleTask`, `SynthesisTask`, `FullProcessTask`, `BatchTask*`.
- **Enums**: `TranscribeModelEnum`, `TranslatorServiceEnum`, `LLMServiceEnum`, `SubtitleLayoutEnum`, `VideoQualityEnum`, `VadMethodEnum`, `BatchTaskType`, `BatchTaskStatus`, `SupportedAudioFormats`, `SupportedVideoFormats`, etc.

---

## Main UI Architecture (`app/view/`)

```
MainWindow (FluentWindow)
├── HomeInterface                    # Main workflow tab interface
│   ├── TaskCreationInterface        # Drag-and-drop video/audio input
│   ├── TranscriptionInterface       # ASR progress display
│   ├── SubtitleInterface            # Subtitle table editor + optimization
│   └── VideoSynthesisInterface      # Final video output
├── BatchProcessInterface            # Multi-file batch processing queue
├── SubtitleStyleInterface           # ASS style preview and selection
└── SettingInterface                 # All LLM/ASR/translate settings
```

The `HomeInterface` is a segmented tab widget. Navigation moves sequentially: Task Creation → Transcription → Subtitle Optimization → Video Synthesis. Each tab transition calls `TaskFactory` to build typed task objects from `cfg` and passes them into threads.

### SubtitleInterface (most complex view)
- Uses `QAbstractTableModel` (`SubtitleTableModel`) to display subtitle data as rows with: start time, end time, original text, translated text.
- Supports real-time update streaming via Qt signals from background threads.
- Has command bar actions for: optimize, translate, merge, split, export (SRT/ASS/VTT/JSON/TXT), LLM video slice analysis.
- Supports direct drag-and-drop of subtitle files.
- Integrates with `slice_analyzer.py` for LLM-driven video slicing.

---

## Thread Architecture (`app/thread/`)

All background work runs in `QThread` subclasses. They communicate progress via `pyqtSignal`:

| Thread | Responsibility |
|---|---|
| `TranscriptThread` | Extracts audio (FFmpeg), runs ASR engine, saves subtitle file |
| `SubtitleThread` | Runs the full subtitle pipeline: split → optimize → translate → save |
| `VideoSynthesisThread` | Calls `add_subtitles()` (FFmpeg) to bake subtitle into video |
| `SubtitlePipelineThread` | Orchestrates TranscriptThread → SubtitleThread → VideoSynthesisThread sequentially |
| `BatchProcessThread` | Processes a queue of files, runs `SubtitlePipelineThread` per file |
| `VideoDownloadThread` | Downloads video via `yt-dlp` |
| `VideoInfoThread` | Probes video metadata via FFmpeg |
| `FileDownloadThread` | Generic file download |
| `ModelScopeDownloadThread` | Downloads Whisper models from ModelScope |
| `VersionCheckerThread` | Checks GitHub releases for updates |

---

## ASR Module (`app/core/asr/`)

### Base Pattern
`BaseASR` (abstract) handles:
- Audio loading from file path or bytes.
- CRC32-based cache key.
- Rate limiting (for free/charity services): max 100 calls and 360 min of audio per 12h window, enforced via diskcache.
- Template: `run()` → tries cache → calls `_run()` → parses via `_make_segments()`.

### Implementations
| Class | Service | Notes |
|---|---|---|
| `BcutASR` | Bilibili Bcut API | Cloud ASR, multipart upload, free |
| `JianYingASR` | JianYing/CapCut (ByteDance) | Cloud ASR, AWS S3-style upload, free |
| `WhisperAPI` | OpenAI-compatible Whisper API | Paid API |
| `FasterWhisperASR` | Local Faster-Whisper binary | Invokes `faster-whisper-xxl.exe` subprocess, supports CUDA, VAD |
| `WhisperCppASR` | Local whisper.cpp | Invokes subprocess |

### ChunkedASR (Decorator Pattern)
`ChunkedASR` wraps any `BaseASR` class to support long audio:
1. Splits audio into overlapping chunks (default 10 min, 10s overlap).
2. Concurrently transcribes all chunks using `ThreadPoolExecutor`.
3. Uses `ChunkMerger` (fuzzy string matching) to deduplicate overlapping segments.

All ASR operations go through `transcribe()` in `asr/transcribe.py` which always wraps in `ChunkedASR`.

---

## Subtitle Processing Pipeline (`app/thread/subtitle_thread.py`)

The `SubtitleThread.run()` implements the full subtitle pipeline:

1. **Word-level decomposition** (if input is sentence-level): calls `asr_data.split_to_word_segments()` which distributes timing proportionally by phoneme count (4 chars/phoneme estimate).
2. **LLM validation**: checks `OPENAI_BASE_URL` and `OPENAI_API_KEY` env vars before any LLM call.
3. **Segmentation** (if word-level data): `SubtitleSplitter` uses LLM to re-segment into natural sentences. Falls back to rule-based splitting if LLM fails.
4. **Optimization** (optional): `SubtitleOptimizer` sends subtitle batches to LLM with agent loop — validates keys, checks similarity ≥ 70% for normal text, retries up to 3 times on failure.
5. **Translation** (optional): `BaseTranslator` dispatches to the selected service (LLM, Bing, Google, DeepLX). Batch processing, parallel threads via `ThreadPoolExecutor`, cached results.
6. **Save**: writes final output as ASS (for video synthesis) or SRT (for subtitle-only mode).

---

## Subtitle Segmentation (`app/core/split/`)

### `SubtitleSplitter`
1. Determines number of LLM segments based on total word count (threshold: 500 words/segment).
2. Splits `ASRData` at natural time gaps near target split points.
3. Concurrently sends each part to LLM via `split_by_llm()`.
4. Uses sliding window + `difflib.SequenceMatcher` to align LLM-returned sentences back to word-level ASR segments.
5. Falls back to rule-based splitting (time gaps + common word splits) if LLM fails.

### Prompts
Prompts are stored as Markdown files in `app/core/prompts/`:
- `split/sentence.md` — sentence segmentation
- `split/semantic.md` — semantic segmentation
- `optimize/subtitle.md` — subtitle correction
- `translate/standard.md` — standard translation
- `translate/reflect.md` — reflective (critic-then-revise) translation
- `translate/single.md` — single sentence fallback
- `analysis/video.md` — video slice analysis

Loaded at runtime via `get_prompt(path, **kwargs)` with Python `string.Template` substitution.

---

## Translation Module (`app/core/translate/`)

### Class Hierarchy
```
BaseTranslator (ABC)
├── LLMTranslator         — OpenAI-compatible API, batch JSON translation
│                           Optional "reflect" mode: critic then native translation
│                           Agent loop with validation (key count, structure)
├── BingTranslator        — Microsoft Translate (free/cookies)
├── GoogleTranslator      — Google Translate (free)
└── DeepLXTranslator      — DeepLX self-hosted proxy
```

`BaseTranslator` handles:
- Splitting subtitle list into batches.
- Parallel batch processing via `ThreadPoolExecutor`.
- Disk caching per class+language+content hash.
- Stop/cleanup via `is_running` flag.

### LLM Translator Agent Loop
1. Send batch as JSON dict `{index: text}` to LLM.
2. Validate response: all keys present, correct structure (for reflect mode: `native_translation` field).
3. On failure: append error feedback and retry (max 3 steps).
4. Fallback to single-sentence mode if batch fails completely.

---

## LLM Client (`app/core/llm/client.py`)

- Singleton `OpenAI` client initialized from `OPENAI_BASE_URL` / `OPENAI_API_KEY` env vars.
- URL normalization: adds `/v1` if path is empty, strips trailing slashes.
- `call_llm()` is decorated with `@memoize(get_llm_cache())` (1h TTL) and `@retry` (tenacity: up to 10 attempts, exponential backoff on `RateLimitError`).
- LLM API key/URL are set as env vars by `SubtitleThread` before calling any LLM functions (per-request override via env vars + singleton reset pattern).

---

## Caching System (`app/core/utils/cache.py`)

Five separate `diskcache.Cache` instances:
- `llm_translation` — LLM API call results (1h TTL via `memoize` decorator).
- `asr_results` — ASR results keyed by audio CRC32 (2-day TTL).
- `translate_results` — Translation batch results (7-day TTL).
- `tts_audio` — TTS audio binary data.
- `version_state` — GitHub version check.

Global toggle via `enable_cache()` / `disable_cache()`. Caching is globally disabled during test runs.

---

## Video Processing (`app/core/utils/video_utils.py`)

Uses FFmpeg subprocess calls for:
- `video2audio()` — extract audio track to MP3/WAV.
- `add_subtitles()` — bake subtitles (hard: `subtitles` filter, soft: `-c:s mov_text`).
- `get_video_info()` — probe metadata via `ffprobe`.
- `get_video_thumbnail()`.

Handles Windows long path (> 260 chars) via `\\?\` prefix.

---

## TTS Module (`app/core/tts/`)

Not exposed in the main UI flow but implemented:

```
BaseTTS (ABC)
├── OpenAITTS      — OpenAI TTS API
├── OpenAIFM       — OpenAI FM (newer audio models)
└── SiliconFlowTTS — SiliconFlow TTS
```

Supports voice cloning: if `clone_audio_path` is set on a `TTSDataSeg`, uses reference audio hash in cache key. Cache stores raw audio bytes (binary).

---

## Configuration System (`app/common/config.py`)

`Config` extends `qfluentwidgets.QConfig`. All settings are `ConfigItem` / `OptionsConfigItem` / `RangeConfigItem` instances with validators and serializers. Persisted to `AppData/settings.json` automatically.

Key config groups:
- `[LLM]` — per-service API base/key/model for 7 LLM providers.
- `[Translate]` — translator service, batch size, thread count, DeepLX endpoint.
- `[Transcribe]` — transcribe model, language, output format.
- `[FasterWhisper]` — model, device, VAD parameters.
- `[WhisperAPI]` — API base/key/model/prompt.
- `[Subtitle]` — optimize/translate flags, split, target language, word count limits, custom prompt.
- `[Video]` — soft subtitle, quality, output.
- `[SubtitleStyle]` — ASS style name, layout (Original on top / Translate on top / Only original / Only translate).
- `[Save]` — work dir.
- `[MainWindow]` — DPI, language, Mica effect.
- `[Cache]` — enabled/disabled.

On macOS, `FasterWhisper` is filtered out from available transcription models automatically.

---

## Subtitle Style System

Subtitle styles are stored as plain text files in `resource/subtitle_style/`:
- `default.txt`
- `毕导科普风.txt` (science vlog style)
- `番剧可爱风.txt` (anime cute style)
- `竖屏.txt` (vertical/portrait)
- `高光背景.txt` (highlight background)

These files contain raw ASS `[V4+ Styles]` section strings. They are loaded by `TaskFactory.get_subtitle_style()` and passed into `asr_data.to_ass(style_str=...)` calls.

---

## Task Factory Pattern (`app/core/task_factory.py`)

`TaskFactory` is a static factory class. All `create_*_task()` methods read directly from the `cfg` singleton and produce fully-configured task dataclasses:
- `create_transcribe_task(file_path, need_next_task)`
- `create_subtitle_task(file_path, video_path, need_next_task)`
- `create_synthesis_task(video_path, subtitle_path)`
- `create_full_process_task(file_path)`
- `create_transcript_and_subtitle_task(file_path)`

Output file naming convention: `【原始字幕】`, `【断句字幕】`, `【样式字幕】`, `【卡卡】` prefixes are used to distinguish processing stages in the work-dir.

---

## Batch Processing

`BatchProcessInterface` shows a `QTableWidget` of queued files. Each row is a `BatchTask` with status (`WAITING`, `RUNNING`, `COMPLETED`, `FAILED`). `BatchProcessThread` dequeues tasks and runs them through `SubtitlePipelineThread` sequentially. Supported batch modes: `TRANSCRIBE`, `SUBTITLE`, `TRANS_SUB`, `FULL_PROCESS`.

---

## Internationalization

Qt `.ts`/`.qm` translation files in `resource/translations/` for:
- `VideoCaptioner_zh_CN` — Simplified Chinese
- `VideoCaptioner_zh_HK` — Traditional Chinese (HK)
- `VideoCaptioner_en_US` — English

The UI strings use `self.tr("...")` throughout. Scripts in `scripts/trans-extract.sh` and `scripts/trans-compile.sh` manage the Qt Linguist workflow.

---

## Testing

Tests are in `tests/`, organized by module:
- `test_asr/` — ASR data, each ASR backend, chunking, chunk merging
- `test_split/` — split logic, alignment, LLM split
- `test_translate/` — each translator backend, cache validation
- `test_optimize/` — subtitle optimizer
- `test_subtitle/` — subtitle thread
- `test_thread/` — pipeline thread, transcript thread, video info, synthesis threads
- `test_tts/` — TTS core and integration

Root `conftest.py` provides shared fixtures:
- `sample_asr_data`, `sample_translate_data`, `target_language`
- `mock_llm_client` — patches `get_llm_client()` to return a `MagicMock` that generates context-aware mock responses (handles split/translate/optimize patterns).
- `check_env_vars` — skips tests if required env vars (API keys) are missing.
- Integration tests require `tests/.env` with `OPENAI_API_KEY`, `OPENAI_BASE_URL`, etc.
- Cache is globally disabled in tests via `cache.disable_cache()`.

Run tests: `pytest` from project root. Run a single file: `pytest tests/test_translate/test_llm_translator.py`.

---

## External Dependencies (System-Level)

- **FFmpeg** — required for audio extraction and video synthesis. Must be on PATH (or in `resource/bin/`).
- **aria2c** (optional) — used for accelerated downloads.
- **Faster-Whisper-XXL binary** — placed in `resource/bin/Faster-Whisper-XXL/`; invoked as subprocess by `FasterWhisperASR`.
- **VLC** (optional) — path configured via `PYTHON_VLC_MODULE_PATH` env var to `resource/bin/vlc`.

---

## Key Design Patterns

1. **Template Method (ASR)** — `BaseASR.run()` defines the skeleton; subclasses implement `_run()` and `_make_segments()`.
2. **Decorator Pattern (ChunkedASR)** — wraps any `BaseASR` subclass, adding chunking transparently.
3. **Agent Loop Pattern** — `LLMTranslator._agent_loop()` and `SubtitleOptimizer.agent_loop()` iterate LLM → validate → feedback → retry up to `MAX_STEPS=3`.
4. **Factory Pattern** — `TaskFactory` centralizes task creation from global config.
5. **Singleton** — `cfg` config object, `_global_client` LLM client.
6. **Signal/Slot** — All thread progress/result communication uses PyQt5 `pyqtSignal`.
7. **Disk Caching** — Multiple `diskcache.Cache` instances, globally toggle-able. Memoize decorator for LLM calls.

---

## Notable Quirks and Specifics

- **`OPENAI_BASE_URL` / `OPENAI_API_KEY` env vars are set at runtime** by `SubtitleThread` before LLM calls, then the singleton `_global_client` must be re-initialized. This works because `get_llm_client()` initializes lazily per process start, but if the key changes mid-session (user edits settings), the global may be stale.
- **`json-repair`** is used throughout to handle LLM JSON output that may be malformed.
- **`langdetect`** is used in `ASRData.from_srt()` to auto-detect bilingual SRT files (checks if 70%+ of 4-line blocks have two different languages on lines 3 and 4).
- **Rate limiting** in `BaseASR._check_rate_limit()` limits free cloud ASR services: 100 calls and 360 min of audio per 12-hour window. Stored in the ASR diskcache with tagged entries.
- **Output file naming**: The work-dir structure is `work-dir/<file_stem>/subtitle/` for intermediate files, and `【卡卡】<stem>.mp4` for final video output.
- **FasterWhisper on macOS** is not available (filtered via `PlatformAwareTranscribeModelValidator`).
- **`SubtitleAligner`** (in `app/core/split/alignment.py`) is used after LLM optimization to re-align text that may have been merged or split differently by the LLM.
- **`slice_analyzer.py`** — an experimental feature allowing LLM-driven selection of thematically relevant video segments (hardcoded to: science, future, AI, space, humanity, technology topics). Uses DeepSeek API directly.
- **Subtitle layout modes**: `TRANSLATE_ON_TOP`, `ORIGINAL_ON_TOP`, `ONLY_ORIGINAL`, `ONLY_TRANSLATE`. In ASS format, original and translated lines use `Default` and `Secondary` styles with different font sizes, rendered at the same timestamp.
