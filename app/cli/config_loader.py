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
    translator_service: str = "llm"

    # Subtitle
    max_word_count_cjk: int = 18
    max_word_count_english: int = 14
    subtitle_layout: str = "translate-on-top"
    subtitle_style: str = "science-vlog"
    batch_size: int = 10
    thread_num: int = 4

    # Video
    need_video: bool = True
    soft_subtitle: bool = False
    video_quality: str = "medium"
    retain_metadata: bool = False
    sync_check: bool = False

    # Glossary learning
    glossary_learn: bool = False
    glossary_save_path: Optional[Path] = None

    # Auto-slice after full processing
    slice_after: bool = False
    slice_topic: str = "the most informative and substantive discussion segments"
    slice_count: int = 5
    slice_context_secs: float = 1.0
    slice_dir: Optional[Path] = None

    # Reframe (landscape → portrait) after video synthesis
    reframe_after: bool = False
    reframe_mode: str = "blur-bg"   # blur-bg | crop-center | split
    reframe_width: int = 1080
    reframe_height: int = 1920
    reframe_blur: int = 40

    # Paths
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    work_dir: Path = field(default_factory=lambda: Path("./work-dir"))
    glossary_path: Optional[Path] = None

    # Glossary data (loaded from file)
    glossary: dict = field(default_factory=dict)

    @classmethod
    def from_args(cls, args: object) -> "CLIConfig":
        cfg = cls()

        # 1. Load from ~/.openvc/config.json
        if OPENVC_CONFIG_FILE.exists():
            with open(OPENVC_CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)

        # 2. Load from explicit --config file
        config_path = getattr(args, "config", None)
        if config_path and Path(config_path).exists():
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)

        # 3. Override with CLI args (fall back to config-file value so
        #    `openvc config set api_key ...` persists correctly)
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

        if getattr(args, "llm_model", None):
            cfg.llm_model = args.llm_model  # type: ignore[union-attr]
        if getattr(args, "model", None):
            cfg.transcribe_model = args.model  # type: ignore[union-attr]
        if getattr(args, "language", None):
            cfg.transcribe_language = args.language  # type: ignore[union-attr]
        if getattr(args, "translate", None):
            cfg.need_translate = True
            cfg.target_language = args.translate  # type: ignore[union-attr]
        if getattr(args, "output", None):
            cfg.output_dir = Path(args.output)  # type: ignore[union-attr]
        if hasattr(args, "no_optimize"):
            cfg.need_optimize = not args.no_optimize  # type: ignore[union-attr]
        if hasattr(args, "post_correct"):
            cfg.post_correct = bool(args.post_correct)  # type: ignore[union-attr]
        if hasattr(args, "retain_metadata"):
            cfg.retain_metadata = bool(getattr(args, "retain_metadata", False))
        if hasattr(args, "sync_check"):
            cfg.sync_check = bool(getattr(args, "sync_check", False))
        if hasattr(args, "no_video"):
            cfg.need_video = not bool(getattr(args, "no_video", False))
        if getattr(args, "quality", None):
            cfg.video_quality = args.quality  # type: ignore[union-attr]
        if hasattr(args, "soft_subtitle"):
            cfg.soft_subtitle = bool(getattr(args, "soft_subtitle", False))
        if getattr(args, "max_cjk", None) is not None:
            cfg.max_word_count_cjk = args.max_cjk  # type: ignore[union-attr]
        if getattr(args, "max_en", None) is not None:
            cfg.max_word_count_english = args.max_en  # type: ignore[union-attr]
        if getattr(args, "batch_size", None) is not None:
            cfg.batch_size = args.batch_size  # type: ignore[union-attr]
        if getattr(args, "threads", None) is not None:
            cfg.thread_num = args.threads  # type: ignore[union-attr]
        if getattr(args, "work_dir", None) is not None:
            cfg.work_dir = Path(args.work_dir)  # type: ignore[union-attr]
        if getattr(args, "translator_service", None):
            cfg.translator_service = args.translator_service  # type: ignore[union-attr]
        if getattr(args, "style", None):
            cfg.subtitle_style = args.style  # type: ignore[union-attr]
        if getattr(args, "layout", None):
            cfg.subtitle_layout = args.layout  # type: ignore[union-attr]
        if hasattr(args, "glossary_learn"):
            cfg.glossary_learn = bool(getattr(args, "glossary_learn", False))
        if getattr(args, "glossary_save", None):
            cfg.glossary_save_path = Path(args.glossary_save)  # type: ignore[union-attr]
        elif cfg.glossary_learn and cfg.glossary_save_path is None:
            cfg.glossary_save_path = OPENVC_GLOSSARY_FILE

        # Reframe options
        if hasattr(args, "reframe") and getattr(args, "reframe", False):
            cfg.reframe_after = True
        if getattr(args, "reframe_mode", None):
            cfg.reframe_mode = args.reframe_mode
        if getattr(args, "reframe_width", None) is not None:
            cfg.reframe_width = args.reframe_width
        if getattr(args, "reframe_height", None) is not None:
            cfg.reframe_height = args.reframe_height
        if getattr(args, "reframe_blur", None) is not None:
            cfg.reframe_blur = args.reframe_blur

        # Slice-after-process options
        if hasattr(args, "slice") and getattr(args, "slice", False):
            cfg.slice_after = True
        if getattr(args, "topic", None):
            cfg.slice_topic = args.topic  # type: ignore[union-attr]
        if getattr(args, "slice_count", None) is not None:
            cfg.slice_count = args.slice_count  # type: ignore[union-attr]
        if getattr(args, "context_secs", None) is not None:
            cfg.slice_context_secs = args.context_secs  # type: ignore[union-attr]
        if getattr(args, "slice_dir", None) is not None:
            cfg.slice_dir = Path(args.slice_dir)  # type: ignore[union-attr]

        # Load glossary file
        glossary_arg = getattr(args, "glossary", None)
        if glossary_arg and Path(glossary_arg).exists():
            cfg.glossary_path = Path(glossary_arg)
            with open(glossary_arg, encoding="utf-8") as f:
                cfg.glossary = json.load(f)
        elif OPENVC_GLOSSARY_FILE.exists() and not glossary_arg:
            with open(OPENVC_GLOSSARY_FILE, encoding="utf-8") as f:
                try:
                    cfg.glossary = json.load(f)
                except Exception:
                    cfg.glossary = {}

        return cfg


def load_persistent_config() -> dict:
    if OPENVC_CONFIG_FILE.exists():
        with open(OPENVC_CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_persistent_config(data: dict) -> None:
    OPENVC_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if OPENVC_CONFIG_FILE.exists():
        with open(OPENVC_CONFIG_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    existing.update(data)
    with open(OPENVC_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
