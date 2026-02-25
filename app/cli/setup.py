"""openVC interactive setup wizard.

Walks through every configurable setting group-by-group, shows current
values as defaults, validates the LLM API key, and saves everything to
~/.openvc/config.json.

Usage:
    openvc setup                 # interactive wizard
    openvc setup --non-interactive  # print current config and exit (CI-friendly)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from app.cli.config_loader import (
    OPENVC_CONFIG_DIR,
    OPENVC_CONFIG_FILE,
    load_persistent_config,
    save_persistent_config,
)

# ── Style & layout choices ─────────────────────────────────────────────────────

_STYLES = ["science-vlog", "default", "anime-cute", "portrait", "highlight-bg"]
_LAYOUTS = ["translate-on-top", "original-on-top", "only-original", "only-translate"]
_QUALITIES = ["medium", "high", "ultra-high", "low"]
_ASR_MODELS = ["bijian", "jianying", "whisper-api", "faster-whisper", "whisper-cpp"]
_TRANSLATORS = ["llm", "bing", "google", "deeplx"]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _hr(title: str = "") -> None:
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def _ask(prompt: str, default: Any, choices: Optional[list] = None, secret: bool = False) -> str:
    """Prompt the user for input, showing the default in brackets.

    Returns the stripped input, or the stringified default if Enter is pressed.
    Validates against choices when provided.
    """
    default_str = str(default) if default not in (None, "") else ""
    display_default = f"[{default_str}] " if default_str else ""

    if choices:
        choice_hint = f"  options: {', '.join(choices)}\n"
        sys.stdout.write(choice_hint)

    while True:
        if secret and default_str:
            display = f"  {prompt} [{'*' * min(len(default_str), 8)}]: "
        else:
            display = f"  {prompt} {display_default}: " if display_default else f"  {prompt}: "

        sys.stdout.write(display)
        sys.stdout.flush()
        try:
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default_str

        value = raw if raw else default_str
        if not value:
            # Required field with no default
            if choices:
                print(f"  Please choose one of: {', '.join(choices)}")
                continue
            return ""

        if choices and value not in choices:
            print(f"  Invalid choice. Options: {', '.join(choices)}")
            continue

        return value


def _test_api_key(api_key: str, base_url: str, model: str) -> bool:
    """Make a minimal LLM call to verify the API key works. Returns True on success."""
    if not api_key:
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return True
    except Exception as exc:
        print(f"  ✗ API test failed: {exc}")
        return False


# ── Section wizards ────────────────────────────────────────────────────────────

def _section_llm(cfg: dict) -> dict:
    _hr("LLM Configuration")
    print("  Used for translation, subtitle optimization, and semantic slicing.\n")

    base_url = _ask("API base URL", cfg.get("base_url", "https://api.openai.com/v1"))
    llm_model = _ask("Default LLM model", cfg.get("llm_model", "gpt-4o-mini"))

    current_key = cfg.get("api_key", os.getenv("OPENAI_API_KEY", ""))
    api_key = _ask("API key", current_key, secret=True)
    if not api_key and current_key:
        api_key = current_key  # keep existing if user pressed Enter

    if api_key:
        sys.stdout.write("  Testing API key... ")
        sys.stdout.flush()
        ok = _test_api_key(api_key, base_url, llm_model)
        print("✓ OK" if ok else "⚠ could not verify (will save anyway)")

    threads = _ask("Parallel LLM threads (lower = fewer rate-limit errors)",
                   cfg.get("thread_num", 4))
    batch_size = _ask("Batch size per LLM call", cfg.get("batch_size", 10))

    return {
        "base_url": base_url,
        "llm_model": llm_model,
        "api_key": api_key,
        "thread_num": _to_int(threads, 4),
        "batch_size": _to_int(batch_size, 10),
    }


def _section_asr(cfg: dict) -> dict:
    _hr("ASR / Transcription")
    print("  Settings for audio-to-text transcription.\n")

    model = _ask("Default ASR model", cfg.get("transcribe_model", "bijian"), _ASR_MODELS)
    language = _ask("Default source language code (e.g. en, zh, ja)",
                    cfg.get("transcribe_language", "en"))

    return {
        "transcribe_model": model,
        "transcribe_language": language,
    }


def _section_translation(cfg: dict) -> dict:
    _hr("Translation")
    print("  Default translation behaviour (can be overridden per-run with --translate).\n")

    need = _ask("Enable translation by default? (y/n)",
                "y" if cfg.get("need_translate", False) else "n")
    result: dict = {"need_translate": need.lower() == "y"}

    if result["need_translate"]:
        target = _ask("Default target language code (e.g. zh, en, ja)",
                      cfg.get("target_language", "zh"))
        result["target_language"] = target

    translator = _ask("Translation service", cfg.get("translator_service", "llm"), _TRANSLATORS)
    result["translator_service"] = translator
    return result


def _section_subtitle(cfg: dict) -> dict:
    _hr("Subtitle Style & Layout")
    print("  Controls how subtitles look in the rendered video.\n")

    style = _ask("Subtitle style preset", cfg.get("subtitle_style", "science-vlog"), _STYLES)
    layout = _ask("Subtitle layout", cfg.get("subtitle_layout", "translate-on-top"), _LAYOUTS)
    max_cjk = _ask("Max CJK characters per line", cfg.get("max_word_count_cjk", 18))
    max_en = _ask("Max English words per line", cfg.get("max_word_count_english", 14))

    return {
        "subtitle_style": style,
        "subtitle_layout": layout,
        "max_word_count_cjk": _to_int(max_cjk, 18),
        "max_word_count_english": _to_int(max_en, 14),
    }


def _section_video(cfg: dict) -> dict:
    _hr("Video Output")
    print("  Controls video synthesis quality and output location.\n")

    quality = _ask("Video quality", cfg.get("video_quality", "medium"), _QUALITIES)
    output_dir = _ask("Default output directory", cfg.get("output_dir", "./output"))
    soft = _ask("Use soft subtitles by default? (y/n)",
                "y" if cfg.get("soft_subtitle", False) else "n")

    return {
        "video_quality": quality,
        "output_dir": str(output_dir),
        "soft_subtitle": soft.lower() == "y",
    }


def _section_advanced(cfg: dict) -> dict:
    _hr("Advanced (optional)")
    print("  Press Enter to keep current values.\n")

    post_correct = _ask("Run LLM ASR post-correction by default? (y/n)",
                        "y" if cfg.get("post_correct", False) else "n")
    sync_check = _ask("Run audio-subtitle drift detection by default? (y/n)",
                      "y" if cfg.get("sync_check", False) else "n")
    retain_meta = _ask("Retain source metadata by default? (y/n)",
                       "y" if cfg.get("retain_metadata", False) else "n")
    glossary_learn = _ask("Enable glossary auto-learning by default? (y/n)",
                          "y" if cfg.get("glossary_learn", False) else "n")

    return {
        "post_correct": post_correct.lower() == "y",
        "sync_check": sync_check.lower() == "y",
        "retain_metadata": retain_meta.lower() == "y",
        "glossary_learn": glossary_learn.lower() == "y",
    }


# ── Summary printer ────────────────────────────────────────────────────────────

def _print_summary(cfg: dict) -> None:
    _hr("Configuration Summary")
    groups = {
        "LLM": ["base_url", "llm_model", "api_key", "thread_num", "batch_size"],
        "ASR": ["transcribe_model", "transcribe_language"],
        "Translation": ["need_translate", "target_language", "translator_service"],
        "Subtitle": ["subtitle_style", "subtitle_layout", "max_word_count_cjk", "max_word_count_english"],
        "Video": ["video_quality", "output_dir", "soft_subtitle"],
        "Advanced": ["post_correct", "sync_check", "retain_metadata", "glossary_learn"],
    }
    for group, keys in groups.items():
        present = {k: cfg[k] for k in keys if k in cfg}
        if not present:
            continue
        print(f"\n  {group}:")
        for k, v in present.items():
            if k == "api_key" and v:
                v = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
            print(f"    {k:<30} {v}")
    print()
    _hr()
    print(f"  Saved to: {OPENVC_CONFIG_FILE}")
    print()


# ── Entry point ────────────────────────────────────────────────────────────────

def run_setup(non_interactive: bool = False) -> int:
    """Run the setup wizard. Returns exit code."""

    OPENVC_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_persistent_config()

    if non_interactive:
        import json
        print(json.dumps(existing, ensure_ascii=False, indent=2))
        return 0

    print("\n🐦 openVC Setup Wizard")
    print("  Press Enter to keep the current value shown in [brackets].")
    print("  Settings are saved to ~/.openvc/config.json\n")

    is_first_run = not OPENVC_CONFIG_FILE.exists()
    if is_first_run:
        print("  First run — no existing config found. Starting fresh.\n")
    else:
        print(f"  Updating existing config at {OPENVC_CONFIG_FILE}\n")

    updated: dict = dict(existing)

    try:
        updated.update(_section_llm(existing))
        updated.update(_section_asr(existing))
        updated.update(_section_translation(existing))
        updated.update(_section_subtitle(existing))
        updated.update(_section_video(existing))
        updated.update(_section_advanced(existing))
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled. No changes saved.")
        return 1

    _hr("Save")
    confirm = _ask("Save this configuration? (y/n)", "y")
    if confirm.lower() != "y":
        print("  Aborted. No changes saved.")
        return 1

    save_persistent_config(updated)
    _print_summary(updated)

    print("  Setup complete. Run `openvc config list` to review at any time.")
    print("  Example: openvc process video.mp4 --translate zh\n")
    return 0
