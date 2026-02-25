import random
from dataclasses import dataclass
from typing import List, Tuple

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.utils.logger import setup_logger

logger = setup_logger("drift_detector")


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
    drift_threshold_ms: int = 200,
    max_correction_ms: int = 1000,
    sample_rate_pct: float = 0.2,
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
