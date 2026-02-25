"""Horizontal → vertical (portrait) video reframing.

Converts landscape video to 9:16 portrait format (TikTok / Reels / Shorts).

Modes
-----
blur-bg      (default) Original video centred on a blurred + zoomed background.
             Classic TikTok look — no black bars, no content cropped away.

crop-center  Simple centre-crop to the target aspect ratio.
             Loses left/right edges but fills the whole frame.

split        Dual-stack: full video on top half, zoomed/blurred on bottom half.
             Useful for wide-screen gaming or landscape lectures.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from app.core.utils.logger import setup_logger

logger = setup_logger("reframe")

_QUALITY_CRF = {"ultra-high": 15, "high": 18, "medium": 22, "low": 28}
_QUALITY_PRESET = {"ultra-high": "slow", "high": "medium", "medium": "medium", "low": "fast"}


# ── ffmpeg filter builders ─────────────────────────────────────────────────────

def _blur_bg_filter(width: int, height: int, blur: int) -> tuple[str, str]:
    """Blurred+zoomed background with original video centred on top."""
    f = (
        # Background: scale to cover the full portrait canvas, then blur
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"boxblur={blur}:6[bg];"
        # Foreground: scale to fit within canvas (no crop)
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        # Overlay fg centred on bg
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
    )
    return f, "out"


def _crop_center_filter(width: int, height: int) -> tuple[str, str]:
    """Centre-crop to portrait aspect ratio."""
    f = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}[out]"
    )
    return f, "out"


def _split_filter(width: int, height: int, blur: int) -> tuple[str, str]:
    """Original (letterboxed) on top half, blurred zoom on bottom half."""
    half = height // 2
    f = (
        # Top: original fitted into top half
        f"[0:v]scale={width}:{half}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{half}:(ow-iw)/2:(oh-ih)/2[top];"
        # Bottom: zoomed+blurred fill
        f"[0:v]scale={width}:{half}:force_original_aspect_ratio=increase,"
        f"crop={width}:{half},"
        f"boxblur={blur}:6[bot];"
        # Stack vertically
        f"[top][bot]vstack[out]"
    )
    return f, "out"


# ── subtitle filter suffix ─────────────────────────────────────────────────────

def _subtitle_suffix(filter_str: str, out_label: str, subtitle_path: str) -> tuple[str, str]:
    """Append ASS/SRT burning to an existing filter graph."""
    safe = subtitle_path.replace("\\", "/").replace(":", "\\:")
    ext = Path(subtitle_path).suffix.lower()
    if ext == ".ass":
        filter_str += f";[{out_label}]ass='{safe}'[subout]"
    else:
        filter_str += f";[{out_label}]subtitles='{safe}'[subout]"
    return filter_str, "subout"


# ── main entry point ───────────────────────────────────────────────────────────

def reframe_video(
    input_path: str,
    output_path: str,
    mode: str = "blur-bg",
    width: int = 1080,
    height: int = 1920,
    blur_strength: int = 40,
    quality: str = "medium",
    subtitle_file: Optional[str] = None,
    progress_callback=None,
) -> str:
    """Convert a landscape video to portrait (TikTok/Reels/Shorts) format.

    Args:
        input_path:        Source video file path.
        output_path:       Destination file path.
        mode:              'blur-bg' | 'crop-center' | 'split'
        width:             Output width  (default 1080).
        height:            Output height (default 1920).
        blur_strength:     Boxblur radius for blur-bg / split modes.
        quality:           Encoding quality: ultra-high / high / medium / low.
        subtitle_file:     Optional ASS/SRT to burn into the reframed video.
        progress_callback: Optional callable(pct, msg) for progress reporting.

    Returns:
        Absolute path to the output file.

    Raises:
        ValueError:  Unknown mode.
        RuntimeError: ffmpeg encoding failure.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    mode = mode.lower()
    if mode == "blur-bg":
        filter_str, out_label = _blur_bg_filter(width, height, blur_strength)
    elif mode == "crop-center":
        filter_str, out_label = _crop_center_filter(width, height)
    elif mode == "split":
        filter_str, out_label = _split_filter(width, height, blur_strength)
    else:
        raise ValueError(f"Unknown reframe mode '{mode}'. Choose: blur-bg, crop-center, split")

    if subtitle_file:
        filter_str, out_label = _subtitle_suffix(
            filter_str, out_label, str(Path(subtitle_file).resolve())
        )

    crf = _QUALITY_CRF.get(quality, 22)
    preset = _QUALITY_PRESET.get(quality, "medium")

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_str,
        "-map", f"[{out_label}]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info(f"Reframing {input_path!r} → {output_path!r}  mode={mode}  {width}x{height}")
    if progress_callback:
        progress_callback(0, f"Reframing ({mode})…")

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")
        logger.error(f"ffmpeg reframe failed:\n{err}")
        raise RuntimeError(f"ffmpeg reframe failed: {err[-500:]}")

    if progress_callback:
        progress_callback(100, "Reframe complete")

    out = str(Path(output_path).resolve())
    logger.info(f"Reframe done → {out}")
    return out
