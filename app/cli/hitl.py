import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.asr.asr_data import ASRData
from app.cli.output import ProgressReporter

STYLE_PRESETS: Dict[str, str] = {
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


class HITLManager:
    def __init__(self, enabled: bool = True, reporter: Optional[ProgressReporter] = None):
        self.enabled = enabled
        self.reporter = reporter

    def checkpoint_transcript(self, asr_data: ASRData, srt_path: Path) -> ASRData:
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

        action = self._prompt({"a": "accept", "e": "edit in $EDITOR", "s": "skip"})
        if action == "e":
            edited_path = self._edit_file(srt_path)
            return ASRData.from_subtitle_file(str(edited_path))
        return asr_data

    def _show_transcript_summary(self, asr_data: ASRData, srt_path: Path) -> None:
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

        sample_indices = [0, total // 2, total - 1] if total >= 3 else list(range(total))
        print("\n  Sample segments:")
        for i in sample_indices:
            seg = segs[i]
            ts = seg.start_time // 1000
            print(f"    [{ts:>4d}s] {seg.text[:80]}")
        print()

    def _flag_transcript_problems(self, asr_data: ASRData) -> List[Tuple[int, str, str]]:
        problems: List[Tuple[int, str, str]] = []
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

    def checkpoint_subtitle(self, asr_data: ASRData) -> ASRData:
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

        action = self._prompt({"a": "accept", "e": "edit SRT in $EDITOR", "s": "skip"})
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

    def _show_translation_summary(self, asr_data: ASRData) -> None:
        import random
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

        sample = random.sample(segs, min(5, total))
        print("\n  Sample pairs (5 random):")
        for seg in sample:
            ts = seg.start_time // 1000
            orig = seg.text[:50]
            trans = (seg.translated_text or "—")[:50]
            print(f"    [{ts:>4d}s] {orig}")
            print(f"           → {trans}")
        print()

    def checkpoint_style(
        self,
        current_style: str = "default",
        style_from_flag: bool = False,
    ) -> str:
        if not self.enabled:
            return current_style
        if not sys.stdin.isatty():
            if self.reporter:
                self.reporter.emit_checkpoint("style_C", {"style": current_style})
            return current_style
        # Skip if user already has a configured default style
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

    def _show_style_menu(self, current: str) -> None:
        print()
        for name, preview in STYLE_PRESETS.items():
            marker = "▶" if name == current else " "
            print(f"  {marker} [{name}]")
            for line in preview.splitlines():
                print(f"      {line}")
            print()

    def _prompt(self, choices: Dict[str, str]) -> str:
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

    def _print_separator(self, title: str) -> None:
        width = 60
        print(f"\n{'─' * width}")
        print(f"  {title}")
        print(f"{'─' * width}")
