import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("trim")


def trim_at_subtitle_boundaries(
    video_path: str,
    asr_data: ASRData,
    segment_ranges: List[Tuple[int, int]],
    output_dir: str,
    context_secs: float = 0.5,
) -> List[str]:
    output_paths: List[str] = []
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    segs = asr_data.segments
    for i, (start_idx, end_idx) in enumerate(segment_ranges):
        if start_idx >= len(segs) or end_idx >= len(segs):
            logger.warning(f"Segment range {start_idx},{end_idx} out of bounds ({len(segs)} segs)")
            continue

        start_ms = max(0, segs[start_idx].start_time - int(context_secs * 1000))
        end_ms = segs[end_idx].end_time + int(context_secs * 1000)

        start_secs = start_ms / 1000
        duration_secs = (end_ms - start_ms) / 1000
        output_path = str(Path(output_dir) / f"clip_{i + 1:03d}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_secs),
            "-i", video_path,
            "-t", str(duration_secs),
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "aac",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            output_paths.append(output_path)
            logger.info(f"Clip {i + 1}: {output_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to trim clip {i + 1}: {e.stderr.decode()}")

    return output_paths


def export_clip_subtitles(
    asr_data: ASRData,
    segment_ranges: List[Tuple[int, int]],
    output_dir: str,
    context_secs: float = 0.5,
    ass_style: Optional[str] = None,
) -> List[str]:
    """Export subtitle files for each clip, with timestamps rebased to clip start.

    Returns list of saved subtitle paths (parallel to segment_ranges).
    """
    from app.core.entities import SubtitleLayoutEnum

    output_paths: List[str] = []
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    segs = asr_data.segments

    for i, (start_idx, end_idx) in enumerate(segment_ranges):
        if start_idx >= len(segs) or end_idx >= len(segs):
            output_paths.append("")
            continue

        offset_ms = max(0, segs[start_idx].start_time - int(context_secs * 1000))
        clip_segs: List[ASRDataSeg] = []
        for seg in segs[start_idx : end_idx + 1]:
            clip_segs.append(ASRDataSeg(
                text=seg.text,
                start_time=max(0, seg.start_time - offset_ms),
                end_time=max(0, seg.end_time - offset_ms),
                translated_text=seg.translated_text,
            ))

        clip_data = ASRData(clip_segs)
        out_path = str(Path(output_dir) / f"clip_{i + 1:03d}.ass")
        clip_data.save(out_path, ass_style=ass_style, layout=SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        output_paths.append(out_path)

    return output_paths
