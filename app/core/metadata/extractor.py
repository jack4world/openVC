import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.asr.asr_data import ASRData
from app.core.utils.logger import setup_logger

logger = setup_logger("metadata")


@dataclass
class VideoMetadata:
    title: str = ""
    source_path: str = ""
    duration_s: float = 0.0
    creation_time: str = ""
    width: int = 0
    height: int = 0
    fps: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    bitrate_kbps: int = 0
    raw_tags: Dict[str, str] = field(default_factory=dict)
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    social_title: str = ""
    social_description: str = ""
    social_tags: List[str] = field(default_factory=list)


def extract_video_metadata(video_path: str) -> VideoMetadata:
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
    tags: Dict[str, str] = fmt.get("tags", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    title = tags.get("title", Path(video_path).stem)
    return VideoMetadata(
        title=title,
        source_path=video_path,
        duration_s=float(fmt.get("duration", 0)),
        creation_time=tags.get("creation_time", ""),
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=str(video_stream.get("r_frame_rate", "")),
        video_codec=str(video_stream.get("codec_name", "")),
        audio_codec=str(audio_stream.get("codec_name", "")),
        bitrate_kbps=int(int(fmt.get("bit_rate", 0)) / 1000),
        raw_tags=tags,
        social_title=title,
        social_description=tags.get("description", tags.get("comment", "")),
        social_tags=tags.get("keywords", "").split(",") if tags.get("keywords") else [],
    )


def generate_chapters_from_subtitles(
    asr_data: ASRData,
    min_chapter_gap_s: float = 30.0,
) -> List[Dict[str, Any]]:
    segs = asr_data.segments
    if not segs:
        return []

    chapters: List[Dict[str, Any]] = [{"start_ms": segs[0].start_time, "title": "Introduction"}]
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
    tmp_output = output_video + ".tmp.mp4"
    ffmeta_path: Optional[str] = None

    if asr_data:
        meta.chapters = generate_chapters_from_subtitles(asr_data)
        ffmeta_path = _write_ffmetadata(meta)

    cmd = ["ffmpeg", "-y", "-i", output_video]
    if ffmeta_path:
        cmd += ["-i", ffmeta_path, "-map_metadata", "1"]
    else:
        cmd += ["-map_metadata", "0"]

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
    lines = [";FFMETADATA1\n", f"title={meta.title}\n\n"]
    for ch in meta.chapters:
        start_ms = ch["start_ms"]
        lines += [
            "[CHAPTER]\n",
            "TIMEBASE=1/1000\n",
            f"START={start_ms}\n",
            f"END={start_ms + 1}\n",
            f"title={ch['title']}\n\n",
        ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ffmeta",
                                     delete=False, encoding="utf-8") as f:
        f.writelines(lines)
        return f.name


def write_sidecar_json(
    output_path: Path,
    meta: VideoMetadata,
    asr_data: Optional[ASRData] = None,
) -> None:
    if asr_data and not meta.chapters:
        meta.chapters = generate_chapters_from_subtitles(asr_data)

    sidecar: Dict[str, Any] = {
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
            "suggested_thumbnail_time_s": round(meta.duration_s * 0.1, 1),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    logger.info(f"Sidecar metadata written: {output_path}")
