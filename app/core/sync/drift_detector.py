import random
from dataclasses import dataclass
from typing import List, Tuple

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("drift_detector")


def snap_subtitles_to_audio_onset(
    asr_data: ASRData,
    audio_path: str,
    lookahead_ms: int = 3000,
    silence_thresh: float = -45.0,
    min_shift_ms: int = 150,
    max_shift_ms: int = 4000,
) -> Tuple[ASRData, int]:
    """Snap each subtitle's start time forward to the nearest speech onset.

    For each segment, if the audio at start_time is below the silence threshold,
    scan forward up to lookahead_ms to find when audio becomes non-silent.
    Shift the segment's start (and end) to that onset, preventing subtitles
    from appearing during silent sections before the corresponding audio plays.

    Args:
        asr_data:       Input subtitle data.
        audio_path:     Path to the source audio file.
        lookahead_ms:   Maximum ms to scan ahead for onset (default 3s).
        silence_thresh: dBFS threshold below which audio is considered silent.
        min_shift_ms:   Ignore onsets within this many ms of start_time (already OK).
        max_shift_ms:   Cap the shift to avoid breaking narrative flow.

    Returns:
        (corrected ASRData, number of segments shifted)
    """
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent
    except ImportError:
        logger.warning("pydub not available, skipping onset snapping")
        return asr_data, 0

    audio = AudioSegment.from_file(audio_path)
    audio_len = len(audio)
    segments = list(asr_data.segments)
    new_segments: List[ASRDataSeg] = []
    shifted = 0

    for seg in segments:
        start = seg.start_time
        if start >= audio_len:
            new_segments.append(seg)
            continue

        # Scan from start_time forward up to lookahead_ms
        scan_end = min(audio_len, start + lookahead_ms)
        window = audio[start:scan_end]

        nonsilent = detect_nonsilent(window, min_silence_len=80, silence_thresh=silence_thresh)

        if not nonsilent:
            # No speech found in lookahead window — keep original
            new_segments.append(seg)
            continue

        onset_offset = nonsilent[0][0]  # ms into the window where speech starts

        if onset_offset < min_shift_ms:
            # Speech starts close to (or at) subtitle start — already correct
            new_segments.append(seg)
            continue

        shift = min(onset_offset, max_shift_ms)
        duration = seg.end_time - seg.start_time
        new_start = start + shift
        new_end = new_start + duration

        logger.debug(
            f"Onset snap: seg[{start}ms] → [{new_start}ms]  (+{shift}ms)"
        )
        new_segments.append(ASRDataSeg(
            text=seg.text,
            start_time=new_start,
            end_time=new_end,
            translated_text=seg.translated_text,
        ))
        shifted += 1

    if shifted:
        logger.info(f"Onset snap: shifted {shifted}/{len(segments)} segments forward")

    return ASRData(new_segments), shifted


@dataclass
class DriftReport:
    segment_index: int
    original_start: int
    detected_start: int
    drift_ms: int
    corrected: bool


def detect_and_correct_drift(
    asr_data: ASRData,
    audio_path: str,
    drift_threshold_ms: int = 80,
    max_correction_ms: int = 2000,
    sample_rate_pct: float = 0.3,
) -> Tuple[ASRData, List[DriftReport]]:
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent
    except ImportError:
        logger.warning("pydub not available, skipping drift detection")
        return asr_data, []

    audio = AudioSegment.from_file(audio_path)
    segments = list(asr_data.segments)
    total = len(segments)
    reports: List[DriftReport] = []

    if total == 0:
        return asr_data, reports

    n_check = max(5, int(total * sample_rate_pct))
    indices_to_check = sorted(random.sample(range(total), min(n_check, total)))

    drifts: List[int] = []
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
            segment_index=idx,
            original_start=seg.start_time,
            detected_start=actual_start_abs,
            drift_ms=drift,
            corrected=False,
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
    new_segments: List[ASRDataSeg] = []
    for seg in segments:
        new_start = max(0, seg.start_time + median_drift)
        new_end = max(new_start + 100, seg.end_time + median_drift)
        new_segments.append(ASRDataSeg(
            text=seg.text,
            start_time=new_start,
            end_time=new_end,
            translated_text=seg.translated_text,
        ))

    for r in reports:
        if abs(r.drift_ms - median_drift) < 100:
            r.corrected = True

    return ASRData(new_segments), reports
