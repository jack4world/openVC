import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    _console = Console()
    _err_console = Console(stderr=True)
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False


def _human_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "?"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.0f} MB"


class ProgressReporter:
    def __init__(self, json_output: bool = False):
        self._json_output = json_output
        self._checkpoints: List[dict] = []
        self._stage_timings: Dict[str, float] = {}
        self._stage_start: Optional[float] = None
        self._current_stage: Optional[str] = None
        self._start_time: float = time.time()

    def stage(self, name: str) -> None:
        self._finish_current_stage()
        self._current_stage = name
        self._stage_start = time.time()
        if not self._json_output and sys.stderr.isatty():
            print(f"  → {name}...", file=sys.stderr)

    def substage(self, message: str) -> None:
        if not self._json_output and sys.stderr.isatty():
            print(f"    • {message}", file=sys.stderr)

    def progress(self, pct: int, message: str) -> None:
        if not self._json_output and sys.stderr.isatty():
            print(f"\r    {message} {pct}%", end="", file=sys.stderr)

    def done(self, message: str) -> None:
        self._finish_current_stage()
        if not self._json_output and sys.stderr.isatty():
            print(f"  ✓ {message}", file=sys.stderr)

    def asr_callback(self, progress: int, message: str) -> None:
        self.progress(progress, message)

    def emit_checkpoint(self, name: str, data: dict) -> None:
        self._checkpoints.append({"checkpoint": name, **data})

    def get_checkpoints(self) -> List[dict]:
        return list(self._checkpoints)

    def elapsed(self) -> float:
        return time.time() - self._start_time

    def record_stage(self, name: str, duration: float) -> None:
        self._stage_timings[name] = duration

    def _finish_current_stage(self) -> None:
        if self._current_stage and self._stage_start is not None:
            self._stage_timings[self._current_stage] = time.time() - self._stage_start
        self._current_stage = None
        self._stage_start = None

    def print_completion_summary(
        self,
        result_files: Dict[str, str],
        stats: Dict[str, Any],
        json_output: bool = False,
    ) -> None:
        if json_output:
            return

        elapsed = self.elapsed()
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        width = 65
        sep = "─" * width
        # Summary always goes to stderr so that stdout stays clean for agents
        # capturing --json-output (this path is only reached in human mode anyway)
        err = sys.stderr

        print(f"\n{sep}", file=err)
        print(f"  openVC  ✓  Pipeline complete  (elapsed: {elapsed_str})", file=err)
        print(sep, file=err)

        file_labels: List[Tuple[str, str, str]] = [
            ("subtitle", "📄 Subtitle (ASS)   ", ""),
            ("video", "🎬 Video            ", ""),
            ("vertical_video", "📱 Portrait (9:16)  ", ""),
            ("portrait_subtitle", "📄 Portrait sub     ", ""),
            ("metadata", "📋 Metadata         ", ""),
            ("raw_transcript", "📝 Raw transcript   ", ""),
        ]
        if any(k in result_files for k, _, _ in file_labels):
            print("\n  Output files:", file=err)
            for key, label, _ in file_labels:
                if key in result_files:
                    p = Path(result_files[key]).resolve()
                    size = _human_size(p)
                    print(f"    {label} {p}   ({size})", file=err)

        print("\n  Processing stats:", file=err)
        segs_total = stats.get("segments_total", 0)
        segs_flagged = stats.get("segments_flagged", 0)
        duration_ms = stats.get("duration_ms", 0)
        dur_mins, dur_secs = divmod(duration_ms // 1000, 60)
        trans_pairs = stats.get("translations", 0)
        trans_warnings = stats.get("untranslated_warnings", 0)
        glossary_applied = stats.get("glossary_terms_applied", 0)
        glossary_learned = stats.get("glossary_terms_learned", 0)

        print(f"    Segments     :  {segs_total} total  ·  {segs_flagged} flagged (HITL A)", file=err)
        if dur_mins or dur_secs:
            print(f"    Duration     :  {dur_mins}m {dur_secs}s", file=err)
        if trans_pairs:
            print(f"    Translations :  {trans_pairs} pairs  ·  {trans_warnings} untranslated warnings", file=err)
        if glossary_applied or glossary_learned:
            print(f"    Glossary     :  {glossary_applied} terms applied  ·  {glossary_learned} new terms learned", file=err)

        stage_parts = []
        for stage_name, secs_f in self._stage_timings.items():
            stage_parts.append(f"{stage_name} {int(secs_f)}s")
        if stage_parts:
            print(f"    Stages       :  {' · '.join(stage_parts)}", file=err)

        print(f"\n{sep}\n", file=err)
