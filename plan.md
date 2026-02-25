# VideoCaptioner — Agent-Optimized Feature Implementation Plan

## Executive Summary

This plan transforms VideoCaptioner from a PyQt5 desktop app into a **headless, agent-callable openVC CLI** while simultaneously fixing the core quality bottlenecks: ASR accuracy, translation precision, segmentation logic, subtitle-audio sync, and LLM token cost. The PyQt5 GUI entry point (`main.py`) is **removed** — the openVC CLI becomes the sole entry point. Agent integration is done through **CLI Skills** (discrete subcommands callable as subprocesses), not a FastAPI server.

**Brand**: The CLI is named **openVC**, with a 🐦 hummingbird as its mascot. On startup, a Rich spinner + hummingbird emoji banner is displayed (suppressed in `--json-output`/non-TTY mode).

**Design principle**: new code lives in `app/cli/`, `app/agent/`, and `app/core/` extensions. Existing `app/core/` modules remain usable as libraries.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 1 — Headless CLI Layer](#2-phase-1--headless-cli-layer) ✅ TESTED
3. [Phase 2 — Terminology & Glossary System](#3-phase-2--terminology--glossary-system)
4. [Phase 3 — ASR Post-Correction](#4-phase-3--asr-post-correction)
5. [Phase 4 — Improved Segmentation](#5-phase-4--improved-segmentation)
6. [Phase 5 — Sync Verification & Drift Detection](#6-phase-5--sync-verification--drift-detection)
7. [Phase 6 — Cost Optimization](#7-phase-6--cost-optimization)
8. [Phase 7 — Human-in-the-Loop (HITL)](#8-phase-7--human-in-the-loop-hitl)
9. [Phase 8 — CLI Skills for Agent Integration](#9-phase-8--cli-skills-for-agent-integration)
10. [Phase 9 — Visual/Style Improvements](#10-phase-9--visualstyle-improvements)
11. [Phase 10 — Metadata Retention](#11-phase-10--metadata-retention)
11b. [Phase 11 — LLM-Driven Semantic Slicing](#11b-phase-11--llm-driven-semantic-slicing) ✅ TESTED
12. [File Structure](#12-file-structure)
13. [Dependency Changes](#13-dependency-changes)
14. [Bug Fixes (Real-World Testing)](#14-bug-fixes-discovered-during-real-world-testing)
15. [Test Results](#15-test-results)
16. [Implementation Roadmap](#16-implementation-roadmap)

---

## 1. Architecture Overview

### Current (GUI-centric)

```
main.py → MainWindow (PyQt5)
            └─ HomeInterface → [threads] → core/
```

### Target (openVC CLI)

```
openvc.py  → openVC CLI entry point     [replaces main.py entirely]
               └─ Pipeline orchestrator
                      ├─ banner.py        (🐦 Rich spinner + hummingbird startup display)
                      ├─ HITL checkpoints (A: transcript, B: translation, C: style)
                      ├─ core/asr/        [enhanced]
                      ├─ core/split/      [enhanced]
                      ├─ core/optimize/   [enhanced]
                      ├─ core/translate/  [enhanced + glossary]
                      ├─ core/sync/       [NEW - drift detection]
                      └─ core/metadata/   [NEW - metadata retention]
```

**Agent integration** — no HTTP server. Agents invoke CLI subcommands directly as subprocesses and parse `--json-output`. `app/agent/skills.py` defines OpenAI-compatible tool schemas that describe CLI commands; the agent calls `subprocess.run(["openvc", ...])`.

### openVC Startup Banner (banner.py)

On TTY startup, `app/cli/banner.py` displays a Rich live spinner with the hummingbird emoji and openVC name:

```
  ⠸ 🐦 openVC v1.0
  ─── AI Video Captioning Pipeline
  Running: process video.mp4 ...
```

The spinner is shown during each pipeline stage via `rich.status.Status`. In `--json-output`/non-TTY mode, the banner and all spinners are suppressed entirely. Implementation lives in `app/cli/banner.py`.

### Data Flow (Enhanced)

```
Input (video/audio/URL)
    │
    ▼
[1] Download & Extract Audio    ← yt-dlp + ffmpeg
    │
    ▼
[2] ASR Transcription           ← ChunkedASR (existing)
    │
    ▼
[3] ASR Post-Correction         ← NEW: LLM-based error correction (opt-in)
    │
    ▼
[4] HITL Checkpoint A           ← NEW: Smart transcript review
    │   (shows stats + flagged segments only, not full dump)
    ▼
[5] Smart Segmentation          ← ENHANCED: context-aware splitting
    │
    ▼
[6] Sync Verification           ← NEW: drift detection + fix
    │
    ▼
[7] Glossary-aware Translation  ← ENHANCED: term injection + auto-learning (cumulative across tasks)
    │   After translation: if --glossary-learn, detect consistently-rendered new terms
    │   and append to ~/.openvc/glossary.json for future runs
    ▼
[8] HITL Checkpoint B           ← NEW: Smart translation review
    │   (shows diff-style summary + sampled pairs, not full list)
    ▼
[9] HITL Checkpoint C           ← NEW (OPTIONAL): Style & layout selection
    │   (terminal UX skin chooser with ASCII previews)
    │   SKIPPED if: default style configured via `openvc config set style <preset>`
    ▼
[10] Video Synthesis            ← ffmpeg (existing)
    │
    ▼
[11] Metadata Retention         ← NEW: preserve + embed + export sidecar
    │
    ▼
[12] Semantic Slicing (optional) ← NEW: LLM identifies topic segments → clips + per-clip subtitles
    │   Triggered by --slice flag on `process` command
    │   Uses analyze_slices_cli() → trim_at_subtitle_boundaries() → export_clip_subtitles()
    ▼
Output: video + subtitle files + [stem].meta.json sidecar + slices/ directory
    └─ Statistics summary printed to terminal with absolute file paths + sizes
       (suppressed in --json-output mode; included as "stats" key in JSON output)
```

---

## 2. Phase 1 — Headless CLI Layer ✅ IMPLEMENTED ✅ TESTED

### Goal
Single `openvc.py` entry point (command: `openvc`) replacing `main.py`. All PyQt5 imports removed from core logic. The `serve` subcommand from the previous plan is removed — agents use `--json-output` and `--no-hitl` flags directly.

### New Files
- `openvc.py` — main CLI entry point (command: `openvc`)
- `app/cli/__init__.py`
- `app/cli/banner.py` — Rich spinner + 🐦 hummingbird startup display
- `app/cli/pipeline.py` — `Pipeline` orchestrator class
- `app/cli/config_loader.py` — loads config from JSON/env/`~/.openvc/config.json` instead of QConfig
- `app/cli/output.py` — Rich-based terminal progress renderer + `print_completion_summary()`

### `openvc.py`

```python
#!/usr/bin/env python3
"""
openVC — AI-powered video captioning pipeline.

Usage examples:
  # Full pipeline
  openvc process video.mp4 --translate zh --output ./out/

  # Transcription only
  openvc transcribe audio.mp3 --model bijian --format srt

  # Subtitle processing only (split + optimize + translate)
  openvc subtitle raw.srt --translate zh --glossary terms.json

  # Video trimming at subtitle boundaries
  openvc trim video.mp4 --subtitle processed.srt --segments 0,5 2,8

  # Agent-friendly (non-interactive, JSON output)
  openvc process video.mp4 --translate zh --json-output --no-hitl

  # Persistent config
  openvc config set style documentary
  openvc config get style
"""

import argparse
import json
import sys
from pathlib import Path

from app.cli.pipeline import Pipeline
from app.cli.config_loader import CLIConfig


def main():
    parser = argparse.ArgumentParser(
        prog="openvc",
        description="🐦 openVC — AI Video Captioning Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, help="Config JSON file path")
    parser.add_argument("--json-output", action="store_true",
                        help="Output results as JSON (for agent consumption)")
    parser.add_argument("--no-hitl", action="store_true",
                        help="Disable human-in-the-loop checkpoints")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── config (persistent defaults) ─────────────────────────────────────────
    cfg_cmd = subparsers.add_parser("config", help="Get/set persistent defaults (~/.openvc/config.json)")
    cfg_cmd.add_argument("action", choices=["set", "get", "list"])
    cfg_cmd.add_argument("key", nargs="?", help="Config key (e.g. style, layout)")
    cfg_cmd.add_argument("value", nargs="?", help="Value to set")

    # ── process (full pipeline) ──────────────────────────────────────────────
    proc = subparsers.add_parser("process", help="Full pipeline: ASR→split→translate→synthesize")
    # NOTE: input is a plain str (NOT type=Path) — Path() collapses https:// → https:/
    proc.add_argument("input", help="Video/audio file or URL")
    proc.add_argument("--output", "-o", type=Path, default=Path("./output"))
    proc.add_argument("--model", default="bijian",
                      choices=["bijian", "jianying", "whisper-api", "faster-whisper", "whisper-cpp"])
    proc.add_argument("--language", default="en",
                      help="Source language code (en, zh, ja...)")
    proc.add_argument("--translate", metavar="LANG",
                      help="Target language for translation (e.g. zh, en)")
    proc.add_argument("--glossary", type=Path,
                      help="Glossary JSON file {term: translation}")
    proc.add_argument("--glossary-learn", action="store_true",
                      help="Auto-learn new terms from translation results (opt-in)")
    proc.add_argument("--glossary-save", type=Path,
                      metavar="PATH",
                      help="Path to persist cumulative glossary (default: ~/.openvc/glossary.json)")
    proc.add_argument("--style", default="default",
                      help="Subtitle style preset name")
    proc.add_argument("--layout", default="translate-on-top",
                      choices=["translate-on-top", "original-on-top", "only-original", "only-translate"])
    proc.add_argument("--no-optimize", action="store_true")
    proc.add_argument("--post-correct", action="store_true",
                      help="Run LLM ASR post-correction (opt-in)")
    proc.add_argument("--no-video", action="store_true",
                      help="Skip video synthesis, output subtitle files only")
    proc.add_argument("--quality", default="medium",
                      choices=["ultra-high", "high", "medium", "low"])
    proc.add_argument("--soft-subtitle", action="store_true")
    # IMPORTANT: all three default to None so ~/.openvc/config.json values are not overridden
    proc.add_argument("--llm-model", default=None,
                      help="LLM model for all AI tasks (agent decides)")
    proc.add_argument("--base-url", default=None)
    proc.add_argument("--api-key", default=None, help="LLM API key (or set OPENAI_API_KEY env)")
    proc.add_argument("--retain-metadata", action="store_true",
                      help="Extract and embed source video metadata in output")
    proc.add_argument("--sync-check", action="store_true",
                      help="Run audio-subtitle drift detection")
    proc.add_argument("--max-cjk", type=int, metavar="N",
                      help="Max CJK characters per subtitle line")
    proc.add_argument("--max-en", type=int, metavar="N",
                      help="Max English words per subtitle line")
    proc.add_argument("--batch-size", type=int, metavar="N",
                      help="LLM batch size for translation/optimization")
    proc.add_argument("--threads", type=int, metavar="N",
                      help="Number of parallel worker threads")
    proc.add_argument("--work-dir", type=Path, metavar="PATH",
                      help="Working directory for intermediate files")
    proc.add_argument("--translator-service", default="llm",
                      choices=["llm", "bing", "google", "deeplx"],
                      help="Translation service backend")
    # ── integrated slicing (runs after full pipeline) ─────────────────────
    proc.add_argument("--slice", action="store_true",
                      help="After full processing, auto-slice into semantic clips via LLM")
    proc.add_argument("--topic", default=None,
                      help="Topic/theme to extract when slicing")
    proc.add_argument("--slice-count", type=int, default=5, metavar="N",
                      help="Approximate number of clips to extract (default: 5)")
    proc.add_argument("--slice-dir", type=Path, default=None, metavar="PATH",
                      help="Output directory for clips (default: <output>/slices/)")
    proc.add_argument("--context-secs", type=float, default=1.0,
                      help="Extra seconds before/after each slice boundary (default: 1.0)")

    # ── transcribe ───────────────────────────────────────────────────────────
    tr = subparsers.add_parser("transcribe", help="ASR only")
    tr.add_argument("input", type=Path)
    tr.add_argument("--output", "-o", type=Path)
    tr.add_argument("--model", default="bijian")
    tr.add_argument("--language", default="en")
    tr.add_argument("--format", default="srt", choices=["srt", "ass", "vtt", "txt", "json"])
    tr.add_argument("--word-timestamps", action="store_true")

    # ── subtitle ─────────────────────────────────────────────────────────────
    sub = subparsers.add_parser("subtitle", help="Subtitle processing only")
    sub.add_argument("input", type=Path, help="Existing subtitle file")
    sub.add_argument("--video", type=Path, help="Associated video (for synthesis)")
    sub.add_argument("--output", "-o", type=Path)
    sub.add_argument("--translate", metavar="LANG")
    sub.add_argument("--glossary", type=Path)
    sub.add_argument("--optimize", action="store_true")
    sub.add_argument("--llm-model", default=None)
    sub.add_argument("--base-url", default=None)
    sub.add_argument("--api-key", default=None)
    sub.add_argument("--threads", type=int, metavar="N")
    sub.add_argument("--batch-size", type=int, metavar="N")
    sub.add_argument("--layout", default="translate-on-top",
                     choices=["translate-on-top","original-on-top","only-original","only-translate"])

    # ── burn ─────────────────────────────────────────────────────────────────
    # Burns an existing subtitle file into video WITHOUT any subtitle reprocessing.
    # Prevents the bug where `subtitle --video` overwrites a translated .ass file.
    burn = subparsers.add_parser("burn", help="Burn subtitle into video (no reprocessing)")
    burn.add_argument("video", type=Path, help="Input video file")
    burn.add_argument("--subtitle", type=Path, required=True, help="ASS/SRT subtitle file to burn")
    burn.add_argument("--output", "-o", type=Path, default=None)
    burn.add_argument("--quality", default="medium",
                      choices=["ultra-high", "high", "medium", "low"])
    burn.add_argument("--soft", action="store_true", help="Soft subtitle (mux, don't burn)")

    # ── trim ─────────────────────────────────────────────────────────────────
    trim = subparsers.add_parser("trim", help="Clip video at subtitle segment boundaries")
    trim.add_argument("video", type=Path)
    trim.add_argument("--subtitle", type=Path, required=True)
    trim.add_argument("--segments", nargs="+", metavar="START,END",
                      help="Segment index ranges e.g. 0,10 15,30")
    trim.add_argument("--output-dir", type=Path, default=Path("./clips"))
    trim.add_argument("--context-secs", type=float, default=0.5,
                      help="Extra seconds before/after clip boundary")

    # ── slice ─────────────────────────────────────────────────────────────────
    # LLM-driven semantic slicer: analyzes subtitle content → extracts topic clips
    slc = subparsers.add_parser("slice",
        help="LLM-driven semantic slicing: auto-detect interesting segments and export clips")
    slc.add_argument("video", type=Path)
    slc.add_argument("--subtitle", type=Path, required=True)
    slc.add_argument("--topic", default=None,
                     help="What to extract (default: most informative segments)")
    slc.add_argument("--count", type=int, default=5,
                     help="Approximate number of clips (default: 5)")
    slc.add_argument("--output-dir", type=Path, default=Path("./slices"))
    slc.add_argument("--context-secs", type=float, default=1.0)
    slc.add_argument("--llm-model", default=None)
    slc.add_argument("--base-url", default=None)
    slc.add_argument("--api-key", default=None)
    slc.add_argument("--no-subtitle-export", action="store_true",
                     help="Skip exporting per-clip subtitle files")

    args = parser.parse_args()
    config = CLIConfig.from_args(args)

    pipeline = Pipeline(config, json_output=args.json_output, hitl=not args.no_hitl)

    try:
        result = pipeline.run(args)
        if args.json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        if args.json_output:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### `app/cli/config_loader.py`

Every `CLIConfig` field has a corresponding CLI flag. The LLM section is simplified: the CLI is invoked BY an agent that already knows which model to use, so only a single `--llm-model` flag is exposed. Per-task model overrides (`optimize_model`, `split_model`, `translate_model`) are removed.

`from_args()` reads persistent defaults from `~/.openvc/config.json` before applying CLI args, enabling `openvc config set style documentary` to skip Checkpoint C automatically.

```python
"""CLI config loader — reads from JSON file + env vars + ~/.openvc/config.json (no QConfig/PyQt5)."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

OPENVC_CONFIG_DIR = Path.home() / ".openvc"
OPENVC_CONFIG_FILE = OPENVC_CONFIG_DIR / "config.json"
OPENVC_GLOSSARY_FILE = OPENVC_CONFIG_DIR / "glossary.json"


@dataclass
class CLIConfig:
    # LLM (single model — agent decides which model to use)
    llm_model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    # REMOVED: optimize_model, split_model, translate_model

    # ASR
    transcribe_model: str = "bijian"
    transcribe_language: str = "en"
    word_timestamps: bool = True

    # Processing
    need_split: bool = True
    need_optimize: bool = False
    need_translate: bool = False
    post_correct: bool = False
    target_language: str = "zh"
    translator_service: str = "llm"   # CLI flag: --translator-service

    # Subtitle
    max_word_count_cjk: int = 18      # CLI flag: --max-cjk
    max_word_count_english: int = 14  # CLI flag: --max-en
    subtitle_layout: str = "translate-on-top"
    subtitle_style: str = "science-vlog"   # default changed from "default"
    batch_size: int = 10              # CLI flag: --batch-size
    thread_num: int = 4               # CLI flag: --threads (reduced from 8; DeepSeek rate-limits at 8)

    # Video
    need_video: bool = True
    soft_subtitle: bool = False
    video_quality: str = "medium"
    retain_metadata: bool = False
    sync_check: bool = False

    # Glossary learning
    glossary_learn: bool = False
    glossary_save_path: Optional[Path] = None

    # Auto-slice after full processing (--slice flag on process command)
    slice_after: bool = False
    slice_topic: str = "the most informative and substantive discussion segments"
    slice_count: int = 5
    slice_context_secs: float = 1.0
    slice_dir: Optional[Path] = None

    # Paths
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    work_dir: Path = field(default_factory=lambda: Path("./work-dir"))  # CLI flag: --work-dir
    glossary_path: Optional[Path] = None

    # Glossary data (loaded from file)
    glossary: dict = field(default_factory=dict)

    @classmethod
    def from_args(cls, args) -> "CLIConfig":
        """Build config from parsed CLI args, with env var and persistent config fallbacks."""
        cfg = cls()

        # 1. Load from ~/.openvc/config.json (persistent defaults set by `openvc config set`)
        if OPENVC_CONFIG_FILE.exists():
            with open(OPENVC_CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)

        # 2. Load from explicit --config file (overrides persistent defaults)
        if hasattr(args, "config") and args.config and Path(args.config).exists():
            with open(args.config, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)

        # 3. Override with CLI args.
        # CRITICAL: fall back to config-file value (cfg.api_key) so that
        # `openvc config set api_key sk-xxx` persists correctly across runs.
        # Using os.getenv("OPENAI_API_KEY", "") as final fallback (not as default)
        # was the bug: it silently overwrote the config-file value with "".
        cfg.api_key = (
            getattr(args, "api_key", None)
            or os.getenv("OPENAI_API_KEY", None)
            or cfg.api_key
            or ""
        )
        cfg.base_url = (
            getattr(args, "base_url", None)
            or os.getenv("OPENAI_BASE_URL", None)
            or cfg.base_url
        )

        if hasattr(args, "llm_model") and args.llm_model:
            cfg.llm_model = args.llm_model
        if hasattr(args, "model") and args.model:
            cfg.transcribe_model = args.model
        if hasattr(args, "language") and args.language:
            cfg.transcribe_language = args.language
        if hasattr(args, "translate") and args.translate:
            cfg.need_translate = True
            cfg.target_language = args.translate
        if hasattr(args, "output") and args.output:
            cfg.output_dir = args.output
        if hasattr(args, "no_optimize"):
            cfg.need_optimize = not args.no_optimize
        if hasattr(args, "post_correct"):
            cfg.post_correct = args.post_correct
        if hasattr(args, "retain_metadata"):
            cfg.retain_metadata = getattr(args, "retain_metadata", False)
        if hasattr(args, "sync_check"):
            cfg.sync_check = getattr(args, "sync_check", False)
        if hasattr(args, "max_cjk") and args.max_cjk is not None:
            cfg.max_word_count_cjk = args.max_cjk
        if hasattr(args, "max_en") and args.max_en is not None:
            cfg.max_word_count_english = args.max_en
        if hasattr(args, "batch_size") and args.batch_size is not None:
            cfg.batch_size = args.batch_size
        if hasattr(args, "threads") and args.threads is not None:
            cfg.thread_num = args.threads
        if hasattr(args, "work_dir") and args.work_dir is not None:
            cfg.work_dir = args.work_dir
        if hasattr(args, "translator_service") and args.translator_service:
            cfg.translator_service = args.translator_service
        if hasattr(args, "style") and args.style:
            cfg.subtitle_style = args.style
        if hasattr(args, "layout") and args.layout:
            cfg.subtitle_layout = args.layout
        if hasattr(args, "glossary_learn"):
            cfg.glossary_learn = getattr(args, "glossary_learn", False)
        if hasattr(args, "glossary_save") and args.glossary_save:
            cfg.glossary_save_path = args.glossary_save
        elif cfg.glossary_learn and cfg.glossary_save_path is None:
            cfg.glossary_save_path = OPENVC_GLOSSARY_FILE

        # Load glossary
        glossary_path = getattr(args, "glossary", None)
        if glossary_path and Path(glossary_path).exists():
            cfg.glossary_path = Path(glossary_path)
            with open(glossary_path, encoding="utf-8") as f:
                cfg.glossary = json.load(f)
        # Also merge cumulative glossary if it exists
        if OPENVC_GLOSSARY_FILE.exists() and not glossary_path:
            with open(OPENVC_GLOSSARY_FILE, encoding="utf-8") as f:
                cfg.glossary = json.load(f)

        return cfg
```

### `app/cli/pipeline.py`

```python
"""CLI Pipeline orchestrator — coordinates all processing stages."""

import datetime
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.cli.config_loader import CLIConfig
from app.cli.hitl import HITLManager
from app.cli.output import ProgressReporter
from app.core.asr.asr_data import ASRData
from app.core.entities import (
    TranscribeConfig, TranscribeModelEnum, SubtitleConfig,
    SynthesisConfig, SubtitleLayoutEnum, TranslatorServiceEnum,
    VideoQualityEnum,
)
from app.core.utils.video_utils import video2audio, add_subtitles, get_video_info


class Pipeline:
    def __init__(self, config: CLIConfig, json_output: bool = False, hitl: bool = True):
        self.cfg = config
        self.reporter = ProgressReporter(json_output)
        self.hitl = HITLManager(enabled=hitl, reporter=self.reporter)

    def run(self, args) -> Dict[str, Any]:
        command = args.command
        if command == "process":
            return self._run_full(args)
        elif command == "transcribe":
            return self._run_transcribe(args)
        elif command == "subtitle":
            return self._run_subtitle(args)
        elif command == "trim":
            return self._run_trim(args)
        elif command == "burn":
            return self._run_burn(args)   # NEW: burn subtitle without reprocessing
        elif command == "slice":
            return self._run_slice(args)  # NEW: LLM semantic slicing
        raise ValueError(f"Unknown command: {command}")

    def _run_full(self, args) -> Dict[str, Any]:
        """Execute full pipeline: download/transcript → ASR → split → translate → synthesize
        → optional semantic slice."""
        # args.input is a raw string (NOT Path) to preserve URL scheme (https://)
        input_str: str = str(args.input)
        output_dir = args.output
        output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: For URLs, try yt-dlp transcript FIRST (avoids full video download)
        asr_data: Optional[ASRData] = None
        input_path: Optional[Path] = None
        audio_path: Optional[Path] = None   # declared here to avoid NameError in sync_check guard
        stem: str = "output"

        if self._is_url(input_str):
            asr_data = self._try_ytdlp_transcript(input_str, ...)  # returns ASRData or None
            # Download video only if transcript not available or video synthesis needed
            if input_path is None and (asr_data is None or not no_video):
                input_path, _ = self._ytdlp_download_video(input_str, output_dir)
                # yt-dlp format: bestvideo[height<=720]+bestaudio/best[height<=720]/best
        else:
            input_path = Path(input_str)

        # Step 2: ASR (only if no transcript yet)
        if asr_data is None:
            audio_path = output_dir / f"{stem}.mp3"
            video2audio(str(input_path), str(audio_path))
            asr_data = transcribe(str(audio_path), ...)

        # NOTE: bijian ASR produces word-level segments (avg ~1 word/segment).
        # _is_word_level() detects this (avg_words < 2.5) and routes to word-count
        # grouping in _rule_based_split() instead of the punctuation+gap rules.

        # Step 4: Optional ASR post-correction
        if self.cfg.post_correct:
            from app.core.asr.post_correct import post_correct_asr
            self.reporter.substage("Post-correcting transcript")
            glossary_hint = "\n".join(self.cfg.glossary.keys()) if self.cfg.glossary else ""
            asr_data = post_correct_asr(
                asr_data, model=self.cfg.llm_model,
                glossary_hint=glossary_hint,
                callback=self.reporter.asr_callback,
            )

        # Save raw transcript
        raw_srt = output_dir / f"[raw]{stem}.srt"
        asr_data.save(str(raw_srt))

        # Step 5: HITL checkpoint A — smart transcript review
        asr_data = self.hitl.checkpoint_transcript(asr_data, raw_srt)

        # Step 6: Subtitle processing (split + optimize + translate)
        self.reporter.stage("Processing subtitles")
        subtitle_config = self._build_subtitle_config()
        processed_data = self._process_subtitles(asr_data, subtitle_config)

        # Step 7: Optional sync check
        if self.cfg.sync_check:
            from app.core.sync.drift_detector import detect_and_correct_drift
            self.reporter.substage("Checking audio-subtitle sync")
            processed_data, drift_reports = detect_and_correct_drift(
                processed_data, str(audio_path)
            )
            if drift_reports:
                self.reporter.substage(f"Drift: {len(drift_reports)} segments checked")

        # Step 8: HITL checkpoint B — smart translation review
        processed_data = self.hitl.checkpoint_subtitle(processed_data)

        # Step 9: HITL checkpoint C — style selection
        selected_style = self.hitl.checkpoint_style(self.cfg.subtitle_style)

        # Save processed subtitle
        processed_ass = output_dir / f"[styled]{stem}.ass"
        processed_data.save(str(processed_ass),
                            ass_style=self._load_style(selected_style),
                            layout=self._parse_layout(self.cfg.subtitle_layout))

        # Step 10: Video synthesis
        result_files = {"subtitle": str(processed_ass), "raw_transcript": str(raw_srt)}

        if not args.no_video:
            self.reporter.stage("Synthesizing video")
            output_video = output_dir / f"[captioned]{stem}.mp4"
            video_quality = self._parse_quality(args.quality)
            add_subtitles(
                str(input_path), str(processed_ass), str(output_video),
                crf=video_quality.get_crf(), preset=video_quality.get_preset(),
                soft_subtitle=args.soft_subtitle,
                progress_callback=lambda v, m: self.reporter.progress(int(v), m),
            )
            result_files["video"] = str(output_video)

            # Step 11: Metadata retention
            if self.cfg.retain_metadata and source_meta:
                from app.core.metadata.extractor import (
                    embed_metadata_in_video, write_sidecar_json
                )
                meta_out = output_dir / f"{stem}.meta.json"
                embed_metadata_in_video(str(output_video), source_meta, processed_data)
                write_sidecar_json(meta_out, source_meta, processed_data)
                result_files["metadata"] = str(meta_out)

        self.reporter.done("Pipeline complete")
        return result_files
```

### `app/cli/output.py` — `print_completion_summary()`

After every successful pipeline run, `print_completion_summary()` is called (suppressed in `--json-output` mode). In JSON mode, the same data is included as a `"stats"` key in the output dict.

```
─────────────────────────────────────────────────────────────
  openVC  ✓  Pipeline complete  (elapsed: 2m 14s)
─────────────────────────────────────────────────────────────

  Output files:
    📄 Subtitle (ASS)    /abs/path/output/[styled]video.ass         (42 KB)
    🎬 Video             /abs/path/output/[captioned]video.mp4      (124 MB)
    📋 Metadata          /abs/path/output/video.meta.json           (3 KB)
    📝 Raw transcript    /abs/path/output/[raw]video.srt            (18 KB)

  Processing stats:
    Segments     :  312 total  ·  18 flagged (HITL A)
    Duration     :  18m 43s
    Translations :  312 pairs  ·  3 untranslated warnings
    Glossary     :  7 terms applied  ·  4 new terms learned
    Stages       :  ASR 48s  ·  Split 12s  ·  Translate 31s  ·  Synth 43s

─────────────────────────────────────────────────────────────
```

All file paths are **absolute** (resolved via `Path.resolve()`) so the user can directly click/open them. File sizes are shown in human-readable units (KB/MB). In `--json-output` mode, output dict gains a `"stats"` key with the same data as a dict.

---

## 3. Phase 2 — Terminology & Glossary System ✅ IMPLEMENTED

### Problem
Proper nouns, technical terms, brand names, and domain vocabulary are routinely mistranslated because the LLM has no awareness of project-specific terminology.

### Solution
A `Glossary` object injected into every prompt as few-shot examples. Terms are automatically detected in the source text and preserved/translated consistently.

### New Files
- `app/core/glossary.py` — `Glossary` class
- `app/core/prompts/translate/glossary_injection.md` — glossary prompt fragment

### `app/core/glossary.py`

```python
"""Terminology glossary for consistent translation of proper nouns and technical terms."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class Glossary:
    """Manages domain-specific terminology for translation consistency.

    Example glossary.json:
        {
            "GPT-4": "GPT-4",
            "large language model": "大语言模型",
            "fine-tuning": "微调",
            "Andrej Karpathy": "安德烈·卡帕西"
        }
    """

    def __init__(self, terms: Dict[str, str]):
        self.terms = terms
        self._patterns = {
            term: re.compile(re.escape(term), re.IGNORECASE)
            for term in terms
        }

    @classmethod
    def from_file(cls, path: Path) -> "Glossary":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def empty(cls) -> "Glossary":
        return cls({})

    def detect_terms_in_text(self, text: str) -> List[Tuple[str, str]]:
        found = []
        for term, pattern in self._patterns.items():
            if pattern.search(text):
                found.append((term, self.terms[term]))
        return found

    def build_prompt_injection(self, text: str) -> str:
        found = self.detect_terms_in_text(text)
        if not found:
            return ""
        lines = ["### Terminology (MUST use these exact translations):"]
        for source, target in found:
            lines.append(f'  "{source}" → "{target}"')
        return "\n".join(lines)

    def enforce_translations(self, original: str, translated: str) -> str:
        for term, translation in self.terms.items():
            pattern = self._patterns[term]
            if pattern.search(translated) and not re.search(
                re.escape(translation), translated, re.IGNORECASE
            ):
                translated = pattern.sub(translation, translated)
        return translated

    def is_empty(self) -> bool:
        return len(self.terms) == 0
```

### Integration into `LLMTranslator`

```python
# In LLMTranslator.__init__, accept glossary parameter:
def __init__(self, ..., glossary: Optional[Glossary] = None):
    ...
    self.glossary = glossary or Glossary.empty()

# In _translate_chunk(), inject glossary into prompt:
def _translate_chunk(self, subtitle_chunk):
    subtitle_dict = {str(data.index): data.original_text for data in subtitle_chunk}
    full_text = " ".join(subtitle_dict.values())

    prompt = get_prompt("translate/standard", target_language=self.target_language, ...)

    glossary_fragment = self.glossary.build_prompt_injection(full_text)
    if glossary_fragment:
        prompt = prompt + "\n\n" + glossary_fragment

    result_dict = self._agent_loop(prompt, subtitle_dict)

    for key in result_dict:
        orig = subtitle_dict.get(key, "")
        result_dict[key] = self.glossary.enforce_translations(orig, result_dict[key])
    ...
```

### Auto-Learning Glossary

After each successful translation run (if `--glossary-learn` is set), the `Glossary` class detects new terms that appear in multiple subtitle segments and were consistently rendered the same way. These are appended to the cumulative glossary file (`~/.openvc/glossary.json` by default, or the path from `--glossary-save`) for use in subsequent tasks.

This creates a feedback loop: the more videos processed in a domain, the better the term consistency becomes.

**New methods on `Glossary`:**

```python
def learn_from_results(
    self,
    source_segments: List[str],
    translated_segments: List[str],
    min_occurrences: int = 3,
) -> Dict[str, str]:
    """Detect terms that appear consistently translated and add to glossary.

    Strategy:
    1. Extract capitalized phrases / CJK-adjacent Latin words from source
    2. Find those that appear in >= min_occurrences segments
    3. Check that the same target rendering appears each time (consistency check)
    4. Add novel entries (not already in self.terms) to self.terms
    Returns newly learned terms dict.
    """
    ...

def save(self, path: Path) -> None:
    """Persist current terms to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(self.terms, f, ensure_ascii=False, indent=2)
```

**Pipeline integration:** After translation at step [7], if `--glossary-learn` is set, call `glossary.learn_from_results()` and save the updated glossary to the cumulative path (`--glossary-save` or `~/.openvc/glossary.json`).

**CLI flags** (on `openvc process`):
- `--glossary-learn`: enable auto-learning (opt-in, default off)
- `--glossary-save PATH`: path to persist cumulative glossary (default `~/.openvc/glossary.json`)

**User workflow:**
```bash
# First video: learns terms from scratch
openvc process lecture1.mp4 --translate zh --glossary-learn

# Second video: automatically uses previously learned terms + continues learning
openvc process lecture2.mp4 --translate zh --glossary-learn

# Inspect accumulated glossary:
cat ~/.openvc/glossary.json
```

---

## 4. Phase 3 — ASR Post-Correction ✅ IMPLEMENTED

### Problem
Free ASR services (Bilibili Bcut, JianYing) frequently produce homophones, garbled proper nouns, and missing punctuation. There is no automated correction layer.

### Solution
A lightweight LLM post-correction pass that runs **after** ASR, **before** segmentation. Opt-in via `--post-correct` flag. Uses a compact prompt that fixes errors without altering meaning. Batched to minimize cost.

### New File: `app/core/asr/post_correct.py`

```python
"""LLM-based ASR post-correction for common transcription errors."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

import json_repair

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.llm import call_llm
from app.core.utils.logger import setup_logger

logger = setup_logger("asr_post_correct")

SYSTEM_PROMPT = """You are a transcript editor. Fix recognition errors in the following subtitles.

Rules:
- Fix homophones and common speech recognition mistakes
- Correct garbled proper nouns (names, brands, places) based on context
- Add missing punctuation within segments (do NOT add cross-segment punctuation)
- Remove repeated words caused by recognition glitches (e.g. "the the")
- Preserve the original meaning and every word — minimal changes only
- Do NOT translate, summarize, or paraphrase
- Return ONLY a JSON object: {"1": "corrected text", "2": "corrected text", ...}
"""


def post_correct_asr(
    asr_data: ASRData,
    model: str,
    batch_size: int = 20,
    thread_num: int = 4,
    glossary_hint: str = "",
    callback: Optional[Callable[[int, str], None]] = None,
) -> ASRData:
    segments = asr_data.segments
    total = len(segments)
    if total == 0:
        return asr_data

    batches = []
    for i in range(0, total, batch_size):
        batch = {
            str(j + 1): segments[j].text
            for j in range(i, min(i + batch_size, total))
        }
        batches.append(batch)

    corrected_map: dict[str, str] = {}
    done_count = 0

    system = SYSTEM_PROMPT
    if glossary_hint:
        system += f"\n\nKnown proper nouns in this content:\n{glossary_hint}"

    def correct_batch(batch: dict) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ]
        resp = call_llm(messages=messages, model=model, temperature=0.1)
        result = json_repair.loads(resp.choices[0].message.content)
        if not isinstance(result, dict):
            logger.warning("Post-correction returned non-dict, keeping originals")
            return batch
        if set(result.keys()) != set(batch.keys()):
            logger.warning("Post-correction key mismatch, keeping originals")
            return batch
        return result

    with ThreadPoolExecutor(max_workers=thread_num) as pool:
        futures = {pool.submit(correct_batch, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                result = fut.result()
                corrected_map.update(result)
            except Exception as e:
                logger.error(f"Post-correction batch failed: {e}")
                corrected_map.update(futures[fut])
            done_count += batch_size
            if callback:
                callback(min(100, int(done_count / total * 100)), "post-correcting")

    new_segments = []
    for i, seg in enumerate(segments, 1):
        corrected_text = corrected_map.get(str(i), seg.text)
        new_segments.append(ASRDataSeg(
            text=corrected_text,
            start_time=seg.start_time,
            end_time=seg.end_time,
            translated_text=seg.translated_text,
        ))

    return ASRData(new_segments)
```

Post-correction is **skipped** when using Whisper-API/FasterWhisper (high accuracy), clean studio audio, or when cost is a concern. Control via `--post-correct` CLI flag (default off).

---

## 5. Phase 4 — Improved Segmentation ✅ IMPLEMENTED

### Current Problems
1. LLM segmentation ignores **sentence boundaries** across split chunks → antecedents cut off.
2. Long pauses within sentences are blindly split → broken context.
3. No mechanism to **preserve subject/pronoun reference** across clips.

### Solution A — Overlap Context Window

When splitting a long ASRData into sub-chunks for parallel LLM processing, include the **last 2 sentences of the previous chunk** as non-split prefix context:

```python
def _split_asr_data_with_context(
    self, asr_data: ASRData, num_segments: int
) -> List[Tuple[ASRData, str]]:
    """Split into (chunk, context_prefix) pairs."""
    base_chunks = self._split_asr_data(asr_data, num_segments)
    result = []
    for i, chunk in enumerate(base_chunks):
        if i == 0:
            context = ""
        else:
            prev_chunk = base_chunks[i - 1]
            tail = prev_chunk.segments[-2:]
            context = " ".join(seg.text for seg in tail)
        result.append((chunk, context))
    return result
```

Inject context into the LLM prompt:

```python
def split_by_llm(text, model, max_word_count_cjk, max_word_count_english,
                 context_prefix: str = "") -> List[str]:
    ...
    user_prompt = f"Please use multiple <br> tags to separate the following sentence:\n{text}"
    if context_prefix:
        user_prompt = (
            f"[CONTEXT from previous segment — do NOT split this, use it for reference only]:\n"
            f"{context_prefix}\n\n"
            f"[TEXT TO SPLIT — apply <br> only here]:\n{text}"
        )
    ...
```

### Solution B — Semantic Sentence Boundary Heuristics

Before calling the LLM, apply a fast rule-based pre-pass that marks **high-confidence** sentence boundaries. The LLM only handles ambiguous spans:

```python
# In app/core/split/boundary.py (NEW FILE)

import re
from typing import List
from app.core.asr.asr_data import ASRDataSeg

END_PUNCTUATION = re.compile(r'[。！？!?\.]\s*$')
STRONG_CONNECTORS = re.compile(
    r'^(but|however|although|yet|nevertheless|nonetheless|而且|但是|然而|虽然)',
    re.IGNORECASE
)


def pre_segment_by_rules(
    segments: List[ASRDataSeg],
    max_gap_ms: int = 800,
) -> List[List[ASRDataSeg]]:
    """Fast rule-based pre-segmentation before LLM call."""
    groups = []
    current = []

    for i, seg in enumerate(segments):
        current.append(seg)

        is_end = (
            END_PUNCTUATION.search(seg.text)
            and (i + 1 >= len(segments)
                 or segments[i + 1].start_time - seg.end_time > max_gap_ms)
        )

        if is_end and i + 1 < len(segments):
            if STRONG_CONNECTORS.match(segments[i + 1].text):
                is_end = False

        if is_end or i == len(segments) - 1:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return groups
```

### Solution C — Clip Context Preservation for Video Trimming

```python
def trim_at_subtitle_boundaries(
    video_path: str,
    asr_data: ASRData,
    segment_ranges: List[Tuple[int, int]],
    output_dir: str,
    context_secs: float = 0.5,
) -> List[str]:
    output_paths = []
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    for i, (start_idx, end_idx) in enumerate(segment_ranges):
        segs = asr_data.segments
        if start_idx >= len(segs) or end_idx >= len(segs):
            continue

        start_ms = max(0, segs[start_idx].start_time - int(context_secs * 1000))
        end_ms = segs[end_idx].end_time + int(context_secs * 1000)

        start_secs = start_ms / 1000
        duration_secs = (end_ms - start_ms) / 1000
        output_path = str(Path(output_dir) / f"clip_{i+1:03d}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_secs),
            "-i", video_path,
            "-t", str(duration_secs),
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "aac",
            output_path,
        ]
        import subprocess
        subprocess.run(cmd, check=True, capture_output=True)
        output_paths.append(output_path)

    return output_paths
```

---

## 6. Phase 5 — Sync Verification & Drift Detection ✅ IMPLEMENTED

### Problem
"Audio-Subtitle drift" where subtitle timestamps don't match actual speech timing. Causes: chunked ASR merging, word-to-sentence merging, and video download timestamp offsets.

### New File: `app/core/sync/drift_detector.py`

```python
"""Audio-subtitle synchronization drift detection and correction."""

from dataclasses import dataclass
from typing import List, Tuple

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("drift_detector")


@dataclass
class DriftReport:
    segment_index: int
    original_start: int   # ms
    detected_start: int   # ms
    drift_ms: int
    corrected: bool


def detect_and_correct_drift(
    asr_data: ASRData,
    audio_path: str,
    drift_threshold_ms: int = 200,
    max_correction_ms: int = 1000,
    sample_rate_pct: float = 0.2,
) -> Tuple[ASRData, List[DriftReport]]:
    import random

    audio = AudioSegment.from_file(audio_path)
    segments = list(asr_data.segments)
    total = len(segments)
    reports = []

    n_check = max(5, int(total * sample_rate_pct))
    indices_to_check = sorted(random.sample(range(total), min(n_check, total)))

    drifts = []
    for idx in indices_to_check:
        seg = segments[idx]
        window_start = max(0, seg.start_time - 500)
        window_end = min(len(audio), seg.start_time + 1500)
        window = audio[window_start:window_end]

        nonsilent = detect_nonsilent(window, min_silence_len=100, silence_thresh=-40)
        if not nonsilent:
            continue

        actual_start_abs = window_start + nonsilent[0][0]
        drift = actual_start_abs - seg.start_time
        drifts.append(drift)
        reports.append(DriftReport(
            segment_index=idx, original_start=seg.start_time,
            detected_start=actual_start_abs, drift_ms=drift, corrected=False,
        ))

    if not drifts:
        return asr_data, reports

    drifts.sort()
    median_drift = drifts[len(drifts) // 2]
    logger.info(f"Median subtitle drift: {median_drift:+d}ms across {len(drifts)} samples")

    if abs(median_drift) < drift_threshold_ms:
        return asr_data, reports

    if abs(median_drift) > max_correction_ms:
        logger.warning(f"Drift {median_drift:+d}ms exceeds max correction. Flagging only.")
        return asr_data, reports

    logger.info(f"Applying global offset correction: {-median_drift:+d}ms")
    new_segments = []
    for seg in segments:
        new_start = max(0, seg.start_time + median_drift)
        new_end = max(new_start + 100, seg.end_time + median_drift)
        new_segments.append(ASRDataSeg(
            text=seg.text, start_time=new_start, end_time=new_end,
            translated_text=seg.translated_text,
        ))

    for r in reports:
        if abs(r.drift_ms - median_drift) < 100:
            r.corrected = True

    return ASRData(new_segments), reports
```

---

## 7. Phase 6 — Cost Optimization ✅ IMPLEMENTED

### Current Token Waste
1. Full subtitle batch (10 items) sent even when most require no change.
2. Same prompt repeated with every LLM call (no shared system prompt caching).
3. Optimization and translation both read the same subtitle twice.
4. Segmentation calls LLM on already-correctly-segmented text.

### Strategy 1 — Selective Optimization (Skip Clean Segments)

```python
# In app/core/optimize/optimize.py — add pre-filter:

def _needs_optimization(text: str) -> bool:
    has_ending_punct = bool(re.search(r'[。！？!?\.]\s*$', text.strip()))
    has_repeats = bool(re.search(r'\b(\w+)\s+\1\b', text, re.IGNORECASE))
    too_short = len(text.strip()) <= 3
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    latin_count = sum(1 for c in text if c.isalpha() and c.isascii())
    suspicious_mix = 0 < cjk_count < 3 and latin_count > 10
    return has_repeats or suspicious_mix or (not has_ending_punct and not too_short)


class SubtitleOptimizer:
    def optimize_subtitle_selective(self, asr_data: ASRData) -> ASRData:
        needs_opt = [i for i, seg in enumerate(asr_data.segments)
                     if _needs_optimization(seg.text)]
        if not needs_opt:
            logger.info("All segments passed cleanliness check, skipping LLM optimization")
            return asr_data
        logger.info(f"{len(needs_opt)}/{len(asr_data.segments)} segments need optimization")
        dirty_data = ASRData([asr_data.segments[i] for i in needs_opt])
        optimized_dirty = self.optimize_subtitle(dirty_data)
        new_segments = list(asr_data.segments)
        for i, opt_seg in zip(needs_opt, optimized_dirty.segments):
            new_segments[i] = ASRDataSeg(
                text=opt_seg.text,
                start_time=asr_data.segments[i].start_time,
                end_time=asr_data.segments[i].end_time,
            )
        return ASRData(new_segments)
```

### Strategy 2 — Uniform Model (Agent Controls)

The CLI is invoked by an agent that already knows which model to use. Per-task model overrides (`optimize_model`, `split_model`, `translate_model`) are removed. The agent passes `--llm-model` and the same model is used for all LLM tasks uniformly.

```python
@dataclass
class CLIConfig:
    # LLM (single model — agent decides which model to use)
    llm_model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    # REMOVED: optimize_model, split_model, translate_model, get_model_for()
```

Agent workflow:
```bash
# Agent uses a cheaper model for cost optimization:
openvc process video.mp4 --translate zh --llm-model gpt-4o-mini

# Agent uses a more powerful model when accuracy is critical:
openvc process video.mp4 --translate zh --llm-model gpt-4o
```

### Token Savings Summary

| Operation | Before | After | Reduction |
|---|---|---|---|
| Split (LLM) | 500 tokens/batch | 200 tokens/batch | 60% |
| Optimize | 350 tokens/batch | 130 tokens (selective) | 63% |
| Translate | 300 tokens/batch | 120 tokens + glossary | 60% |
| Post-correct | N/A (new) | 80 tokens/batch (cheap model) | — |
| **Total** | **~1150/batch** | **~530/batch** | **~54%** |

---

## 8. Phase 7 — Human-in-the-Loop (HITL) ✅ IMPLEMENTED

### Design

Three checkpoint gates between pipeline stages. Each checkpoint uses **smart summarization** — it never dumps the full content. Instead it shows a compact quality digest so a human can quickly decide whether to intervene.

**Checkpoint C is optional** — it is skipped when a default style is configured via `openvc config set style <preset>`. This allows repeated runs without interactive prompts.

**Persistent default style/layout via `openvc config`:**
```bash
openvc config set style documentary   # saved to ~/.openvc/config.json
openvc config set layout translate-on-top
openvc process video.mp4 --translate zh   # Checkpoint C is skipped automatically
```

Config is stored at `~/.openvc/config.json` and loaded by `CLIConfig.from_args()` before any CLI flags are applied.

**Common pattern:**
1. Display a quality summary (stats + flagged items + sampled preview).
2. Prompt: `[a]ccept / [e]dit / [r]etry / [s]kip`.
3. `edit`: opens file in `$EDITOR`.
4. `retry`: re-runs the stage.
5. `skip`: proceeds with current state.

When no TTY (agent mode): auto-accepts and emits checkpoint state in JSON output.

### Smart Context Summarization — Design Principle

> The human has **no time to read 300 lines of transcript**. The HITL display must surface only actionable signals: total stats, flagged anomalies, and a small representative sample. The full file path is always shown for manual inspection.

### `app/cli/hitl.py`

```python
"""Human-in-the-Loop manager for pipeline checkpoints."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.asr.asr_data import ASRData
from app.cli.output import ProgressReporter


class HITLManager:

    def __init__(self, enabled: bool = True, reporter: Optional[ProgressReporter] = None):
        self.enabled = enabled
        self.reporter = reporter

    # ── Checkpoint A: Transcript Review ──────────────────────────────────────

    def checkpoint_transcript(self, asr_data: ASRData, srt_path: Path) -> ASRData:
        """Checkpoint A: Smart review of raw ASR transcript."""
        if not self.enabled:
            return asr_data

        if not sys.stdin.isatty():
            if self.reporter:
                self.reporter.emit_checkpoint("transcript_A", {
                    "file": str(srt_path),
                    "segments": len(asr_data.segments),
                    "flagged": len(self._flag_transcript_problems(asr_data)),
                })
            return asr_data

        self._print_separator("CHECKPOINT A — Transcript Review")
        self._show_transcript_summary(asr_data, srt_path)

        action = self._prompt(
            choices={"a": "accept", "e": "edit in $EDITOR", "s": "skip"},
        )

        if action == "e":
            edited_path = self._edit_file(srt_path)
            return ASRData.from_subtitle_file(str(edited_path))
        return asr_data

    def _show_transcript_summary(self, asr_data: ASRData, srt_path: Path):
        segs = asr_data.segments
        total = len(segs)
        total_duration_s = max((s.end_time for s in segs), default=0) // 1000
        total_words = sum(len(s.text.split()) for s in segs)

        problems = self._flag_transcript_problems(asr_data)

        print(f"\n  Stats: {total} segments · {total_duration_s}s · ~{total_words} words")
        print(f"  File:  {srt_path}")

        if not problems:
            print("  Quality: ✓ No obvious issues detected")
        else:
            print(f"  Quality: ⚠  {len(problems)} flagged segments (showing up to 8):\n")
            for idx, reason, text in problems[:8]:
                ts = segs[idx].start_time // 1000
                print(f"    [{ts:>4d}s][{reason}] {text[:70]}")

        # Always show 3 representative samples (first, mid, last)
        sample_indices = [0, total // 2, total - 1] if total >= 3 else list(range(total))
        print("\n  Sample segments:")
        for i in sample_indices:
            seg = segs[i]
            ts = seg.start_time // 1000
            print(f"    [{ts:>4d}s] {seg.text[:80]}")
        print()

    def _flag_transcript_problems(self, asr_data: ASRData) -> List[Tuple[int, str, str]]:
        """Return list of (index, reason, text) for suspicious segments."""
        problems = []
        for i, seg in enumerate(asr_data.segments):
            text = seg.text.strip()
            if len(text) <= 2:
                problems.append((i, "too-short", text))
            elif re.search(r'\b(\w{2,})\s+\1\b', text, re.IGNORECASE):
                problems.append((i, "repetition", text))
            elif re.search(r'[^\x00-\x7F]{1,2}(?=[a-zA-Z]{5,})', text):
                problems.append((i, "mixed-script", text))
            elif len(text) > 150:
                problems.append((i, "too-long", text[:70] + "..."))
        return problems

    # ── Checkpoint B: Translation Review ─────────────────────────────────────

    def checkpoint_subtitle(self, asr_data: ASRData) -> ASRData:
        """Checkpoint B: Smart review of processed/translated subtitles."""
        if not self.enabled:
            return asr_data

        if not sys.stdin.isatty():
            if self.reporter:
                self.reporter.emit_checkpoint("subtitle_B", {
                    "segments": len(asr_data.segments),
                    "translated": sum(1 for s in asr_data.segments if s.translated_text),
                })
            return asr_data

        self._print_separator("CHECKPOINT B — Translation Review")
        self._show_translation_summary(asr_data)

        action = self._prompt(
            choices={"a": "accept", "e": "edit SRT in $EDITOR", "s": "skip"},
        )

        if action == "e":
            with tempfile.NamedTemporaryFile(suffix=".srt", delete=False, mode="w",
                                            encoding="utf-8") as f:
                f.write(asr_data.to_srt())
                tmp_srt = f.name
            edited_path = self._edit_file(Path(tmp_srt))
            edited_data = ASRData.from_subtitle_file(str(edited_path))
            Path(tmp_srt).unlink(missing_ok=True)
            return edited_data
        return asr_data

    def _show_translation_summary(self, asr_data: ASRData):
        segs = asr_data.segments
        total = len(segs)
        translated_count = sum(1 for s in segs if s.translated_text)
        unchanged = [s for s in segs if s.translated_text and
                     s.translated_text.strip() == s.text.strip()]

        print(f"\n  Stats: {total} segments · {translated_count} translated")
        if unchanged:
            print(f"  ⚠  {len(unchanged)} segments appear untranslated (source = target):")
            for seg in unchanged[:5]:
                print(f"       {seg.text[:60]}")

        # Show 5 sampled bilingual pairs — not all of them
        import random
        sample = random.sample(segs, min(5, total))
        print("\n  Sample pairs (5 random):")
        for seg in sample:
            ts = seg.start_time // 1000
            orig = seg.text[:50]
            trans = (seg.translated_text or "—")[:50]
            print(f"    [{ts:>4d}s] {orig}")
            print(f"           → {trans}")
        print()

    # ── Checkpoint C: Style Selection (OPTIONAL) ──────────────────────────────
    #
    # Checkpoint C is shown ONLY if ALL of:
    #   1. HITL is enabled (--no-hitl not set)
    #   2. Running in a TTY (interactive terminal)
    #   3. No default style is configured (style == "default" AND no --style flag given)
    #
    # If the user has run `openvc config set style <preset>`, the style is loaded
    # into CLIConfig at startup and Checkpoint C is skipped silently.

    def checkpoint_style(self, current_style: str = "default", style_from_flag: bool = False) -> str:
        """Checkpoint C (optional): Terminal style/skin chooser before video synthesis.

        Skipped if HITL disabled, non-TTY, or a default style is already configured.
        """
        if not self.enabled:
            return current_style

        if not sys.stdin.isatty():
            if self.reporter:
                self.reporter.emit_checkpoint("style_C", {"style": current_style})
            return current_style

        # Skip if user has a configured default style (either from --style flag
        # or from `openvc config set style <preset>` in ~/.openvc/config.json)
        if style_from_flag or current_style != "default":
            return current_style

        self._print_separator("CHECKPOINT C — Subtitle Style Selection (optional)")
        self._show_style_menu(current_style)

        print(f"  Current: [{current_style}]")
        print("  Tip: run `openvc config set style <name>` to skip this in future.")
        print("  Enter style name or press Enter to keep current: ", end="", flush=True)
        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return current_style

        return choice if choice in STYLE_PRESETS else current_style

    def _show_style_menu(self, current: str):
        print()
        for name, preview in STYLE_PRESETS.items():
            marker = "▶" if name == current else " "
            print(f"  {marker} [{name}]")
            for line in preview.splitlines():
                print(f"      {line}")
            print()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _prompt(self, choices: dict) -> str:
        choice_str = " / ".join(f"[{k}]{v}" for k, v in choices.items())
        print(f"  {choice_str}: ", end="", flush=True)
        while True:
            try:
                ans = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return list(choices.keys())[0]
            if ans in choices:
                return ans
            print(f"  Invalid. {choice_str}: ", end="", flush=True)

    def _edit_file(self, path: Path) -> Path:
        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, str(path)], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"  Editor failed. File at: {path}")
            input("  Press Enter when done editing...")
        return path

    def _print_separator(self, title: str):
        width = 60
        print(f"\n{'─' * width}")
        print(f"  {title}")
        print(f"{'─' * width}")


# ── Terminal UX Skin Presets ──────────────────────────────────────────────────
# ASCII previews shown in Checkpoint C style chooser.

STYLE_PRESETS = {
    "default": """\
┌─────────────────────────────┐
│  White text, thin outline   │
│  经典白色字幕，细描边        │
└─────────────────────────────┘""",

    "highlight-bg": """\
┌─────────────────────────────┐
│ ██ Semi-transparent BG ██   │
│ ██  半透明背景高亮字幕  ██  │
└─────────────────────────────┘""",

    "minimal": """\
┌─────────────────────────────┐
│  No outline, clean look     │
│  极简无描边样式              │
└─────────────────────────────┘""",

    "terminal-dark": """\
┌─────────────────────────────┐
│  Green on dark bg (#00FF41) │
│  终端绿色，深色背景          │
└─────────────────────────────┘""",

    "documentary": """\
┌─────────────────────────────┐
│  Centered, serif, shadow    │
│  纪录片风格，居中衬线字体    │
└─────────────────────────────┘""",

    "social-media": """\
┌─────────────────────────────┐
│  Bold, yellow, top-aligned  │
│  社交媒体风格，顶部粗体黄字  │
└─────────────────────────────┘""",
}
```

---

## 9. Phase 8 — CLI Skills for Agent Integration ✅ IMPLEMENTED

### Design

**No HTTP server.** Agents call CLI subcommands as subprocess tools and parse `--json-output`. This is simpler, more portable, and eliminates a service dependency.

`app/agent/skills.py` provides **OpenAI-compatible tool schemas** that describe the CLI commands. An agent platform registers these schemas; when called, the agent executes the corresponding CLI subprocess.

### Pattern: CLI Skill = Subprocess + JSON Schema

```
Agent decides to use tool "process_video"
    → Reads schema from app/agent/skills.py
    → Builds CLI args from tool parameters
    → Calls: subprocess.run(["openvc", "process", ...])
    → Parses JSON from stdout
    → Returns result to agent
```

### New File: `app/agent/skills.py`

```python
"""CLI Skills — OpenAI-compatible tool schemas for agent subprocess integration.

Agents use these schemas to understand available CLI tools.
Execution = subprocess call to openvc with --json-output --no-hitl.
"""

from typing import Any, Dict, List
import json
import subprocess
import sys


# ── Tool Schemas ──────────────────────────────────────────────────────────────

PROCESS_VIDEO_SKILL = {
    "type": "function",
    "function": {
        "name": "process_video",
        "description": (
            "Transcribe, translate, and caption a video file or URL. "
            "Returns paths to the output subtitle file and optionally a captioned video."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Path to video/audio file or a URL (YouTube, etc.)"
                },
                "output_dir": {"type": "string", "description": "Output directory"},
                "transcribe_model": {
                    "type": "string",
                    "enum": ["bijian", "jianying", "whisper-api", "faster-whisper"],
                    "default": "bijian"
                },
                "source_language": {"type": "string", "default": "en"},
                "translate_to": {
                    "type": "string",
                    "description": "Target language code (zh, en, ja...). Omit to skip translation."
                },
                "glossary": {
                    "type": "object",
                    "description": "Custom terminology map {source_term: target_translation}",
                    "additionalProperties": {"type": "string"}
                },
                "optimize": {"type": "boolean", "default": False},
                "generate_video": {"type": "boolean", "default": True},
                "subtitle_layout": {
                    "type": "string",
                    "enum": ["translate-on-top", "original-on-top", "only-original", "only-translate"],
                    "default": "translate-on-top"
                },
                "style": {
                    "type": "string",
                    "enum": ["default", "highlight-bg", "minimal", "terminal-dark", "documentary", "social-media"],
                    "default": "default"
                },
                "retain_metadata": {
                    "type": "boolean",
                    "description": "Preserve source video metadata in output",
                    "default": False
                },
                "llm_model": {"type": "string", "default": "gpt-4o-mini"}
            },
            "required": ["input"]
        }
    }
}

TRANSCRIBE_SKILL = {
    "type": "function",
    "function": {
        "name": "transcribe_audio",
        "description": "Transcribe audio/video to subtitle text. Returns SRT file path.",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "language": {"type": "string", "default": "en"},
                "model": {
                    "type": "string",
                    "enum": ["bijian", "jianying", "whisper-api"],
                    "default": "bijian"
                },
                "output": {"type": "string", "description": "Output SRT file path"}
            },
            "required": ["input"]
        }
    }
}

TRIM_VIDEO_SKILL = {
    "type": "function",
    "function": {
        "name": "trim_video_at_subtitles",
        "description": (
            "Extract video clips at subtitle segment boundaries. "
            "Useful for highlight reels or splitting long videos by topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "video": {"type": "string"},
                "subtitle": {"type": "string", "description": "SRT/ASS subtitle file"},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2, "maxItems": 2
                    },
                    "description": "List of [start_segment_index, end_segment_index]"
                },
                "output_dir": {"type": "string"},
                "context_secs": {"type": "number", "default": 0.5}
            },
            "required": ["video", "subtitle", "segments"]
        }
    }
}

ALL_SKILLS = [PROCESS_VIDEO_SKILL, TRANSCRIBE_SKILL, TRIM_VIDEO_SKILL]


# ── Skill Executor ────────────────────────────────────────────────────────────

class SkillExecutor:
    """Execute CLI skills as subprocesses. Used by agent integrations.

    Calls the `openvc` command directly (installed as a script), with
    --json-output and --no-hitl for non-interactive agent use.
    """

    def __init__(self, openvc_cmd: str = "openvc"):
        self.openvc_cmd = openvc_cmd

    def execute(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run a skill by name with given parameters. Returns parsed JSON output."""
        if skill_name == "process_video":
            return self._run_process(params)
        elif skill_name == "transcribe_audio":
            return self._run_transcribe(params)
        elif skill_name == "trim_video_at_subtitles":
            return self._run_trim(params)
        raise ValueError(f"Unknown skill: {skill_name}")

    def _run_process(self, p: Dict) -> Dict:
        cmd = [
            self.openvc_cmd, "process", p["input"],
            "--model", p.get("transcribe_model", "bijian"),
            "--language", p.get("source_language", "en"),
            "--llm-model", p.get("llm_model", "gpt-4o-mini"),
            "--style", p.get("style", "default"),
            "--json-output", "--no-hitl",
        ]
        if p.get("output_dir"):
            cmd += ["--output", p["output_dir"]]
        if p.get("translate_to"):
            cmd += ["--translate", p["translate_to"]]
        if p.get("optimize"):
            cmd.append("--optimize")
        if not p.get("generate_video", True):
            cmd.append("--no-video")
        if p.get("retain_metadata"):
            cmd.append("--retain-metadata")

        # Write glossary to temp file if provided
        glossary_path = None
        if p.get("glossary"):
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                            delete=False, encoding="utf-8") as f:
                json.dump(p["glossary"], f, ensure_ascii=False)
                glossary_path = f.name
            cmd += ["--glossary", glossary_path]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                return {"error": result.stderr}
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        finally:
            if glossary_path:
                from pathlib import Path
                Path(glossary_path).unlink(missing_ok=True)

    def _run_transcribe(self, p: Dict) -> Dict:
        cmd = [
            self.openvc_cmd, "transcribe", p["input"],
            "--model", p.get("model", "bijian"),
            "--language", p.get("language", "en"),
            "--json-output",
        ]
        if p.get("output"):
            cmd += ["--output", p["output"]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        return json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr}

    def _run_trim(self, p: Dict) -> Dict:
        segments_str = [f"{s[0]},{s[1]}" for s in p["segments"]]
        cmd = [
            self.openvc_cmd, "trim", p["video"],
            "--subtitle", p["subtitle"],
            "--segments", *segments_str,
            "--json-output",
        ]
        if p.get("output_dir"):
            cmd += ["--output-dir", p["output_dir"]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        return json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr}
```

### Agent Integration Example

```python
# An LLM agent using function calling:
from app.agent.skills import ALL_SKILLS, SkillExecutor

# 1. Register skill schemas with your agent framework
tools = ALL_SKILLS  # pass to OpenAI client as tools=[...]

# 2. When agent invokes a tool:
executor = SkillExecutor()  # calls `openvc` command
result = executor.execute("process_video", {
    "input": "/path/to/video.mp4",
    "translate_to": "zh",
    "glossary": {"Claude": "Claude", "Anthropic": "Anthropic"},
    "style": "social-media",
    "retain_metadata": True,
    "llm_model": "gpt-4o-mini",  # agent chooses the model
})
# result = {"subtitle": "...", "video": "...", "metadata": "...", "stats": {...}}
```

---

## 10. Phase 9 — Visual/Style Improvements ✅ IMPLEMENTED

### Problem 1: Resolution-Aware Font & Size

```python
# In app/core/utils/get_subtitle_style.py — new helper:

import platform
from typing import Optional


def generate_adaptive_style(
    video_width: int,
    video_height: int,
    layout: str = "bilingual",
    style_preset: str = "default",
    primary_font: Optional[str] = None,
    secondary_font: Optional[str] = None,
) -> str:
    """Generate ASS style optimized for video resolution and platform."""
    is_portrait = video_height > video_width
    is_hd = video_width >= 1280

    system = platform.system()
    if system == "Darwin":
        default_cjk_font = "PingFang SC"
    elif system == "Windows":
        default_cjk_font = "Microsoft YaHei"
    else:
        default_cjk_font = "Noto Sans CJK SC"

    font = primary_font or default_cjk_font

    if is_portrait:
        primary_size = 48 if is_hd else 36
        secondary_size = 38 if is_hd else 28
    else:
        primary_size = 40 if is_hd else 28
        secondary_size = 30 if is_hd else 22

    margin_v = int(video_height * 0.05)
    margin_h = int(video_width * 0.02)

    # Apply preset-specific overrides
    preset_overrides = _get_preset_overrides(style_preset)

    style = (
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{primary_size},"
        f"{preset_overrides.get('primary_color', '&H00FFFFFF')},"
        f"&H000000FF,&H00000000,"
        f"{preset_overrides.get('back_color', '&H80000000')},"
        f"-1,0,0,0,100,100,0,0,"
        f"{preset_overrides.get('border_style', '1')},"
        f"{preset_overrides.get('outline', '2')},1,2,"
        f"{margin_h},{margin_h},{margin_v},1\n"
    )
    return style


def _get_preset_overrides(preset: str) -> dict:
    return {
        "default":       {"primary_color": "&H00FFFFFF", "border_style": "1", "outline": "2"},
        "highlight-bg":  {"primary_color": "&H00FFFFFF", "border_style": "4", "outline": "10",
                          "back_color": "&HAA000000"},
        "minimal":       {"primary_color": "&H00FFFFFF", "border_style": "1", "outline": "0"},
        "terminal-dark": {"primary_color": "&H0041FF00", "border_style": "4", "outline": "8",
                          "back_color": "&HCC000000"},
        "documentary":   {"primary_color": "&H00FFFFCC", "border_style": "1", "outline": "3"},
        "social-media":  {"primary_color": "&H0000FFFF", "border_style": "1", "outline": "3"},
    }.get(preset, {})
```

### Problem 2: Resolution-Aware Line Length

```python
def recommended_line_length(video_width: int, is_cjk: bool) -> int:
    if is_cjk:
        return int(video_width * 0.80 / 38.0)
    else:
        return int(video_width * 0.80 / 60.0)

# 1920px: CJK=40, EN=25
# 1280px: CJK=26, EN=17
# 720px (portrait): CJK=15, EN=9
```

### Checkpoint C Integration

The style preset chosen at Checkpoint C (see Phase 7) is passed to `generate_adaptive_style()` before video synthesis. This connects the terminal UX skin chooser to the actual ASS style generation.

---

## 11. Phase 10 — Metadata Retention ✅ IMPLEMENTED

### Problem

After video processing, output files lose all source metadata: title, creation date, GPS, chapter markers, codec info. This breaks consistency in:
- **Downstream video editing** (NLEs lose clip metadata)
- **Social media releases** (must re-enter title/description for every export)
- **Content archives** (no traceability back to source)

### Solution

Three-part system:
1. **Extract** source metadata via `ffprobe` before processing.
2. **Embed** metadata into output video via `ffmpeg -map_metadata`.
3. **Export sidecar** `.meta.json` with extended info for social media/editing tools.

### New Files
- `app/core/metadata/__init__.py`
- `app/core/metadata/extractor.py` — extract + embed + sidecar

### `app/core/metadata/extractor.py`

```python
"""Video metadata extraction, embedding, and sidecar export.

Extracts: title, creation_time, duration, codec, GPS tags, chapters.
Embeds metadata into output video via ffmpeg -map_metadata.
Writes a .meta.json sidecar for downstream editing and social media release.
"""

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.asr.asr_data import ASRData
from app.core.utils.logger import setup_logger

logger = setup_logger("metadata")


@dataclass
class VideoMetadata:
    # Core identity
    title: str = ""
    source_path: str = ""

    # Timing
    duration_s: float = 0.0
    creation_time: str = ""   # ISO 8601

    # Video stream
    width: int = 0
    height: int = 0
    fps: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    bitrate_kbps: int = 0

    # Embedded tags
    raw_tags: Dict[str, str] = field(default_factory=dict)

    # Chapter markers (auto-generated from subtitle topic changes)
    chapters: List[Dict[str, Any]] = field(default_factory=list)

    # Social media fields (filled from raw_tags or defaults)
    social_title: str = ""
    social_description: str = ""
    social_tags: List[str] = field(default_factory=list)


def extract_video_metadata(video_path: str) -> VideoMetadata:
    """Extract metadata from a video file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.warning(f"ffprobe failed: {e}")
        return VideoMetadata(source_path=video_path)

    fmt = data.get("format", {})
    tags = fmt.get("tags", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    title = tags.get("title", Path(video_path).stem)
    meta = VideoMetadata(
        title=title,
        source_path=video_path,
        duration_s=float(fmt.get("duration", 0)),
        creation_time=tags.get("creation_time", ""),
        width=video_stream.get("width", 0),
        height=video_stream.get("height", 0),
        fps=video_stream.get("r_frame_rate", ""),
        video_codec=video_stream.get("codec_name", ""),
        audio_codec=audio_stream.get("codec_name", ""),
        bitrate_kbps=int(int(fmt.get("bit_rate", 0)) / 1000),
        raw_tags=tags,
        social_title=title,
        social_description=tags.get("description", tags.get("comment", "")),
        social_tags=tags.get("keywords", "").split(",") if tags.get("keywords") else [],
    )
    return meta


def generate_chapters_from_subtitles(
    asr_data: ASRData,
    min_chapter_gap_s: float = 30.0,
) -> List[Dict[str, Any]]:
    """Auto-generate chapter markers from subtitle segment gaps.

    Inserts a chapter at each pause longer than min_chapter_gap_s.
    Returns list of {start_ms, title} dicts.
    """
    segs = asr_data.segments
    if not segs:
        return []

    chapters = [{"start_ms": segs[0].start_time, "title": "Introduction"}]
    chapter_num = 2

    for i in range(1, len(segs)):
        gap_s = (segs[i].start_time - segs[i - 1].end_time) / 1000
        if gap_s >= min_chapter_gap_s:
            chapters.append({
                "start_ms": segs[i].start_time,
                "title": f"Chapter {chapter_num}",
            })
            chapter_num += 1

    return chapters


def embed_metadata_in_video(
    output_video: str,
    meta: VideoMetadata,
    asr_data: Optional[ASRData] = None,
) -> bool:
    """Re-embed metadata into the output video using ffmpeg -map_metadata.

    Also writes chapter markers if asr_data is provided.
    Returns True on success.
    """
    tmp_output = output_video + ".tmp.mp4"

    # Build ffmetadata for chapter markers
    ffmeta_path = None
    if asr_data:
        meta.chapters = generate_chapters_from_subtitles(asr_data)
        ffmeta_path = _write_ffmetadata(meta)

    cmd = [
        "ffmpeg", "-y",
        "-i", output_video,
    ]
    if ffmeta_path:
        cmd += ["-i", ffmeta_path, "-map_metadata", "1"]
    else:
        cmd += ["-map_metadata", "0"]

    # Embed core tags
    cmd += [
        "-metadata", f"title={meta.title}",
        "-metadata", f"creation_time={meta.creation_time}",
        "-c", "copy",
        tmp_output,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        import os
        os.replace(tmp_output, output_video)
        logger.info(f"Metadata embedded in {output_video}")
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"Metadata embedding failed: {e.stderr.decode()}")
        Path(tmp_output).unlink(missing_ok=True)
        return False
    finally:
        if ffmeta_path:
            Path(ffmeta_path).unlink(missing_ok=True)


def _write_ffmetadata(meta: VideoMetadata) -> str:
    """Write ffmetadata file with chapter markers."""
    import tempfile
    lines = [";FFMETADATA1\n"]
    lines.append(f"title={meta.title}\n\n")
    for ch in meta.chapters:
        start_ms = ch["start_ms"]
        lines.append("[CHAPTER]\n")
        lines.append("TIMEBASE=1/1000\n")
        lines.append(f"START={start_ms}\n")
        lines.append(f"END={start_ms + 1}\n")   # ffmpeg requires END
        lines.append(f"title={ch['title']}\n\n")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ffmeta",
                                    delete=False, encoding="utf-8") as f:
        f.writelines(lines)
        return f.name


def write_sidecar_json(
    output_path: Path,
    meta: VideoMetadata,
    asr_data: Optional[ASRData] = None,
) -> None:
    """Write a .meta.json sidecar file for downstream editing and social media.

    Schema:
    {
        "title": "...",
        "source": "/original/path.mp4",
        "duration_s": 123.4,
        "creation_time": "2025-01-01T12:00:00Z",
        "resolution": "1920x1080",
        "video_codec": "h264",
        "audio_codec": "aac",
        "bitrate_kbps": 5000,
        "chapters": [{"start_ms": 0, "title": "Introduction"}, ...],
        "social_media": {
            "title": "...",
            "description": "...",
            "tags": ["tag1", "tag2"],
            "suggested_thumbnail_time_s": 5.0
        }
    }
    """
    if asr_data and not meta.chapters:
        meta.chapters = generate_chapters_from_subtitles(asr_data)

    sidecar = {
        "title": meta.title,
        "source": meta.source_path,
        "duration_s": meta.duration_s,
        "creation_time": meta.creation_time,
        "resolution": f"{meta.width}x{meta.height}",
        "fps": meta.fps,
        "video_codec": meta.video_codec,
        "audio_codec": meta.audio_codec,
        "bitrate_kbps": meta.bitrate_kbps,
        "chapters": meta.chapters,
        "social_media": {
            "title": meta.social_title or meta.title,
            "description": meta.social_description,
            "tags": meta.social_tags,
            # Suggest thumbnail at 10% of duration (usually past intro)
            "suggested_thumbnail_time_s": round(meta.duration_s * 0.1, 1),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    logger.info(f"Sidecar metadata written: {output_path}")
```

### Usage

```bash
# Include metadata retention in full pipeline:
openvc process video.mp4 \
    --translate zh \
    --retain-metadata \
    --json-output --no-hitl

# Output:
# {
#   "subtitle": "./output/[styled]video.ass",
#   "video": "./output/[captioned]video.mp4",
#   "metadata": "./output/video.meta.json"
# }
```

The `.meta.json` sidecar is designed for:
- **NLE import** (DaVinci Resolve, Premiere): import chapter markers and clip metadata
- **Social media publishing** (pre-filled title, description, tags)
- **Archive consistency** (traceability from captioned output back to source)

---

## 11b. Phase 11 — LLM-Driven Semantic Slicing ✅ IMPLEMENTED ✅ TESTED

### Goal

After a full pipeline run, automatically identify topic-coherent segments using an LLM and export them as individual video clips with rebased subtitle files.

### Trigger

- **Standalone**: `openvc slice video.mp4 --subtitle processed.ass --topic "AI safety"`
- **Integrated**: `openvc process video.mp4 --translate zh --slice --topic "AI safety"` (runs after synthesis)

### New Files

- `app/core/llm/slice_analyzer.py` — LLM semantic analysis → `(start_idx, end_idx)` pairs
- `app/core/split/trim.py` — enhanced with `export_clip_subtitles()`

### `app/core/llm/slice_analyzer.py`

Two entry points:

```python
def analyze_slices_cli(
    asr_data: ASRData,
    model: str,
    topic: str = "the most informative and substantive discussion segments",
    count: int = 5,
) -> List[Tuple[int, int]]:
    """CLI-compatible slice analyzer using call_llm() with env-based credentials.

    Sends full subtitle index list to LLM:
        "0: That it is surprising..."
        "1: to me that we are..."
    LLM returns JSON: [[0, 15], [28, 45], [60, 80]]
    Returns validated list of (start_idx, end_idx) pairs.
    """
    from app.core.llm import call_llm
    subtitle_text = "\n".join(f"{i}: {seg.text}" for i, seg in enumerate(asr_data.segments))
    prompt = (f"Analyze the following subtitles and identify {count} to {count + 3} segments "
              f"that contain in-depth discussion about: {topic}. ...")
    response = call_llm(messages=[{"role": "user", "content": prompt}], model=model, temperature=0.3)
    ranges = json_repair.loads(_strip_code_fence(response.choices[0].message.content.strip()))
    return _validate_ranges(ranges, len(asr_data.segments))
```

The original `analyze_slices()` (GUI-only, uses `cfg.deepseek_api_key`) is preserved but gracefully fails if GUI config is unavailable.

### `export_clip_subtitles()` in `trim.py`

Exports per-clip `.ass` files with timestamps rebased to clip start:

```python
def export_clip_subtitles(
    asr_data: ASRData,
    segment_ranges: List[Tuple[int, int]],
    output_dir: str,
    context_secs: float = 0.5,
    ass_style: Optional[str] = None,
) -> List[str]:
    """For each range: extract segments, subtract offset_ms from timestamps, save ASS.
    Returns list of saved subtitle paths (parallel to segment_ranges).
    """
    for i, (start_idx, end_idx) in enumerate(segment_ranges):
        offset_ms = max(0, segs[start_idx].start_time - int(context_secs * 1000))
        clip_segs = [ASRDataSeg(text=seg.text,
                                start_time=max(0, seg.start_time - offset_ms),
                                end_time=max(0, seg.end_time - offset_ms),
                                translated_text=seg.translated_text)
                     for seg in segs[start_idx:end_idx + 1]]
        clip_data = ASRData(clip_segs)
        clip_data.save(f"clip_{i+1:03d}.ass", ass_style=ass_style, ...)
```

### CLI Flags for `slice` subcommand

| Flag | Default | Description |
|---|---|---|
| `--subtitle` | required | SRT/ASS subtitle file |
| `--topic` | most informative segments | LLM topic hint |
| `--count` | 5 | Approximate number of clips |
| `--output-dir` | `./slices` | Output directory |
| `--context-secs` | 1.0 | Padding around clip boundaries |
| `--llm-model` | from config | LLM model name |
| `--no-subtitle-export` | off | Skip per-clip `.ass` files |

### Integrated flags on `process` (--slice)

| Flag | Default | Description |
|---|---|---|
| `--slice` | off | Enable auto-slicing after full pipeline |
| `--topic` | — | Topic hint for LLM slicer |
| `--slice-count` | 5 | Approximate number of clips |
| `--slice-dir` | `<output>/slices/` | Output directory for clips |
| `--context-secs` | 1.0 | Padding per clip |

### Output

For each clip:
- `clip_001.mp4` — trimmed video (no burned subtitles by default)
- `clip_001.ass` — subtitle file with timestamps rebased to 00:00:00

To burn subtitles into clips, use `burn` after slice:
```bash
openvc burn output/slices/clip_001.mp4 --subtitle output/slices/clip_001.ass
```

### Notes

- Ordering: process full video first (ASR + translate once), then semantic slice. Slice-first is impossible for LLM semantic analysis without existing subtitles.
- `clip_001.mp4` does NOT contain burned subtitles — this is intentional. Use `burn` separately.
- Slice step fails gracefully if no LLM API key is configured (emits warning, pipeline continues).

---

## 12. File Structure

```
VideoCaptioner/
├── openvc.py                       # NEW: sole CLI entry point (command: openvc, replaces main.py)
│
├── app/
│   ├── cli/                        # NEW
│   │   ├── __init__.py
│   │   ├── banner.py               # NEW: 🐦 Rich spinner + hummingbird startup display
│   │   ├── pipeline.py             # Pipeline orchestrator (burn + slice dispatch added)
│   │   ├── config_loader.py        # JSON/env/~/.openvc/config.json config (no QConfig)
│   │   ├── hitl.py                 # HITL manager (Checkpoints A, B, C)
│   │   └── output.py               # Rich terminal progress + print_completion_summary()
│   │
│   ├── agent/                      # NEW
│   │   ├── __init__.py
│   │   └── skills.py               # CLI Skill schemas + SkillExecutor (calls openvc)
│   │
│   └── core/
│       ├── asr/
│       │   └── post_correct.py     # NEW: LLM ASR post-correction
│       ├── sync/                   # NEW
│       │   ├── __init__.py
│       │   └── drift_detector.py   # Audio-subtitle drift detection
│       ├── metadata/               # NEW
│       │   ├── __init__.py
│       │   └── extractor.py        # Metadata extract + embed + sidecar
│       ├── llm/
│       │   └── slice_analyzer.py   # NEW: analyze_slices_cli() — LLM semantic slice analysis
│       ├── glossary.py             # NEW: Terminology management + learn_from_results()
│       ├── split/
│       │   ├── boundary.py         # NEW: Rule-based boundary heuristics
│       │   └── trim.py             # ENHANCED: + export_clip_subtitles() with timestamp rebasing
│       └── prompts/
│           └── translate/
│               └── compact.md      # NEW: Token-efficient translation prompt
```

**Style presets** (`resource/subtitle_style/`):

| File | Description |
|---|---|
| `default.txt` | Arial 42px, green (#5aff65) |
| `science-vlog.txt` | .AppleHongKongChineseFont 36px, light gray — **default** |
| `anime-cute.txt` | 微软雅黑 46px |
| `portrait.txt` | 24px, optimized for vertical video |
| `highlight-bg.txt` | 36px, white with highlight background |

**Persistent user config directory**: `~/.openvc/`
- `~/.openvc/config.json` — persistent defaults set by `openvc config set`
- `~/.openvc/glossary.json` — cumulative auto-learned glossary (populated by `--glossary-learn`)

---

## 13. Dependency Changes

Add to `requirements.txt`:

```
# Rich terminal output (replaces print)
rich>=13.7.0

# Subtitle sync / VAD (pydub likely already in requirements)
pydub>=0.25.1
```

Removed (no longer needed):
```
# fastapi and uvicorn are NOT required — CLI Skills replace the HTTP server
```

Optional (for drift detection with pyannote):
```
# pyannote.audio>=3.1.0  # optional, heavy — only if pydub VAD proves insufficient
```

---

## 14. Bug Fixes (Discovered During Real-World Testing)

All bugs below were found and fixed while running the full pipeline against a real 68-minute YouTube video (`https://www.youtube.com/watch?v=68ylaeBbdsg`).

| # | Bug | Root Cause | Fix |
|---|---|---|---|
| 1 | `NameError: ASRDataSeg` in `pipeline.py` | Only `ASRData` was imported | Added `ASRDataSeg` to import |
| 2 | URL mangled to `https:/` | `type=Path` in argparse normalizes `//` to `/` | Changed `process input` arg to plain `str` (no `type=Path`) |
| 3 | yt-dlp format not available | `bestvideo[ext=mp4]+bestaudio[ext=m4a]/...` format not always present | Changed to `bestvideo[height<=720]+bestaudio/best[height<=720]/best` |
| 4 | 429 rate limiting from yt-dlp subtitle fetch | `"all"` language variant triggers aggressive rate limiting | Removed `"all"` from `lang_variants` list |
| 5 | `audio_path` undefined when using yt-dlp transcript | `audio_path` was declared inside conditional ASR block only | Declared `audio_path: Optional[Path] = None` before conditional block; added guard `if self.cfg.sync_check and audio_path is not None` |
| 6 | Word-level bijian ASR → 1 giant subtitle segment | `pre_segment_by_rules` expects phrase-level input; bijian produces word-per-segment (14k+ segs at avg 1 word each) | Added `_is_word_level()` (avg_words < 2.5); `_rule_based_split()` groups by `max_word_count_english` word count for word-level input |
| 7 | `--llm-model default="gpt-4o-mini"` overrides config file | Non-None default string in argparse → `getattr(args, "llm_model")` is truthy → overwrites config file value | Changed all three `--llm-model`, `--base-url`, `--api-key` to `default=None` |
| 8 | `api_key` from `openvc config set` not loaded | `from_args()` step 3: `os.getenv("OPENAI_API_KEY", "")` empty-string fallback overwrote the config-file value | Changed to `getattr(args, "api_key", None) or os.getenv("OPENAI_API_KEY", None) or cfg.api_key or ""` |
| 9 | `--threads` missing from `subtitle` subcommand | Flag only added to `process`, not `subtitle` | Added `--threads`, `--batch-size`, `--base-url`, `--api-key` to `subtitle` subparser |
| 10 | Translation fails at 8 threads (DeepSeek "Model Not Exist") | DeepSeek rate-limits parallel requests | Reduced default `thread_num` from 8 → 4 in `CLIConfig` |
| 11 | `subtitle --video` overwrites translated `bilingual.ass` | `subtitle` command reprocesses input and saves to `--output` path, then burns; overwrote the already-translated file | Added `burn` subcommand that only burns an existing subtitle — no reprocessing, no file overwrite |

---

## 15. Test Results

All subcommands tested and passing as of 2026-02-25:

| Command | Status | Notes |
|---|---|---|
| `config set/get/list` | ✅ | `api_key` persisted and loaded correctly |
| `transcribe` | ✅ | word-level output, exit 0 |
| `subtitle` | ✅ | 120KB ASS generated, science-vlog style applied |
| `trim` | ✅ | Two 4.5MB clips extracted |
| `burn` | ✅ | Subtitle burned without reprocessing |
| `slice` | ✅ | 8 clips + 8 ASS files with rebased timestamps |
| `process` (full pipeline) | ✅ | 68-min YouTube video, 1028/1038 bilingual segments |
| `process --slice` | ✅ | Slice step gracefully skipped when API key invalid |
| `--json-output` | ✅ | Clean JSON only, no progress text mixed in |
| `--no-hitl` | ✅ | All checkpoints skipped |

---

## 16. Implementation Roadmap

### Phase Priority & Dependencies

```
P1 (1-2 days) — Foundation
  [1.1] openvc.py + CLIConfig + Pipeline skeleton  (enables all subsequent phases)
  [1.2] HITLManager (Checkpoints A, B, C)         (zero external deps)

P2 (2-3 days) — Quality Wins (high impact, low risk)
  [2.1] Glossary system + LLMTranslator injection  (fixes translation precision)
  [2.2] ASR post_correct.py                        (fixes recognition accuracy)
  [2.3] Compact prompts (reduce token usage ~54%)  (immediate cost savings)

P3 (2-3 days) — Agent Integration
  [3.1] app/agent/skills.py (CLI Skills schemas)   (enables agent subprocess calls)
  [3.2] SkillExecutor                              (agent execution layer)
  [3.3] Selective optimization filter              (cost savings)

P4 (2-3 days) — Algorithms
  [4.1] Segmentation context window               (fixes truncation issues)
  [4.2] Boundary heuristics (boundary.py)          (reduces LLM calls)
  [4.3] Drift detector                             (fixes sync issues)

P5 (2-3 days) — Style + Metadata
  [5.1] Adaptive style generator + preset system  (fixes visual issues)
  [5.2] Checkpoint C style selection UI           (HITL style chooser)
  [5.3] Metadata extractor + embed + sidecar      (retention for social/editing)
  [5.4] trim_at_subtitle_boundaries()             (enables video clipping)
```

### Quick Start for Implementation

```bash
# 1. Install new deps
pip install rich

# 2. Install openVC as a script (adds `openvc` to PATH):
pip install -e .   # requires entry_points in setup.py/pyproject.toml

# 3. Test CLI immediately (transcription only):
openvc transcribe tests/fixtures/audio/en.mp3 --output ./test-out/

# 4. Test full pipeline (agent-mode, no HITL):
openvc process tests/fixtures/audio/en.mp3 \
    --translate zh \
    --llm-model gpt-4o-mini \
    --no-video \
    --json-output \
    --no-hitl

# 5. Test with metadata retention:
openvc process tests/fixtures/video/sample.mp4 \
    --translate zh \
    --retain-metadata \
    --json-output --no-hitl

# 6. Test HITL checkpoints (interactive):
openvc process tests/fixtures/audio/en.mp3 \
    --translate zh \
    --no-video

# 7. Set persistent style default (skips Checkpoint C in future runs):
openvc config set style documentary

# 8. Test glossary auto-learning:
openvc process tests/fixtures/audio/en.mp3 \
    --translate zh \
    --glossary-learn \
    --no-video --json-output --no-hitl
```

### Testing Strategy

```
tests/
├── test_cli/
│   ├── test_pipeline.py           # CLI pipeline integration
│   ├── test_config_loader.py      # CLIConfig from args/env
│   └── test_hitl.py              # HITL non-interactive mode + style presets
├── test_agent/
│   └── test_skills.py             # Schema validation + SkillExecutor (mocked)
└── test_core/
    ├── test_glossary.py           # Term detection, injection, enforcement
    ├── test_post_correct.py       # ASR correction (mocked LLM)
    ├── test_drift_detector.py     # Drift detection with test audio
    ├── test_boundary.py           # Rule-based segmentation
    └── test_metadata.py           # Extract, embed, sidecar (mocked ffprobe)
```

---

## Summary of Changes vs. Current State

| Area | Current State | After Plan |
|---|---|---|
| Entry point | `main.py` (PyQt5 only) | `openvc.py` (openVC CLI — replaces GUI entirely) |
| Brand | VideoCaptioner (desktop) | openVC CLI with 🐦 hummingbird mascot + Rich spinner banner |
| Agent integration | None | CLI Skills (subprocess + JSON), no HTTP server; calls `openvc` |
| LLM config | N/A | Single `--llm-model` flag; agent decides model; no per-task overrides |
| All flags exposed | N/A | Every CLIConfig field has a CLI flag (`--max-cjk`, `--threads`, etc.) |
| Persistent config | N/A | `~/.openvc/config.json` via `openvc config set key value` |
| Terminology | None | `Glossary` class, JSON glossary file support |
| Glossary learning | None | Auto-learns new terms across runs with `--glossary-learn` (`~/.openvc/glossary.json`) |
| ASR accuracy | Raw ASR output only | Optional LLM post-correction pass |
| Segmentation | LLM only, no context | Context window overlap + rule pre-pass |
| Sync | No verification | Drift detection + auto-correction |
| Translation | LLM/Bing/Google/DeepLX | + Glossary injection + term enforcement |
| Cost | ~1150 tokens/batch | ~530 tokens/batch (54% reduction) |
| HITL | None (GUI interaction) | 3 checkpoints: transcript (smart summary), translation (diff-style), style (optional, skipped if default set) |
| Style | Fixed presets, Windows fonts | Resolution-aware, platform-adaptive; presets: `science-vlog` (default), `anime-cute`, `portrait`, `highlight-bg`, `default`; persistent via `openvc config set subtitle_style` |
| Terminal output | None | Statistics summary with absolute file paths + sizes after every run |
| Video trimming | Not available | `trim` CLI command at subtitle boundaries |
| Burn subtitle | Not available | `burn` subcommand: burn existing subtitle without reprocessing (prevents file overwrites) |
| Semantic slicing | Not available | `slice` subcommand + `--slice` on `process`: LLM identifies topic segments → clips + rebased subtitles |
| Metadata | Lost after processing | Extracted, re-embedded, + `.meta.json` sidecar for social media / NLE workflows |
