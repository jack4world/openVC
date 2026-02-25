import re
from typing import List

from app.core.asr.asr_data import ASRDataSeg

_END_PUNCTUATION = re.compile(r'[。！？!?\.]\s*$')
_STRONG_CONNECTORS = re.compile(
    r'^(but|however|although|yet|nevertheless|nonetheless|而且|但是|然而|虽然)',
    re.IGNORECASE,
)


def pre_segment_by_rules(
    segments: List[ASRDataSeg],
    max_gap_ms: int = 800,
) -> List[List[ASRDataSeg]]:
    groups: List[List[ASRDataSeg]] = []
    current: List[ASRDataSeg] = []

    for i, seg in enumerate(segments):
        current.append(seg)

        is_end = (
            bool(_END_PUNCTUATION.search(seg.text))
            and (
                i + 1 >= len(segments)
                or segments[i + 1].start_time - seg.end_time > max_gap_ms
            )
        )

        if is_end and i + 1 < len(segments):
            if _STRONG_CONNECTORS.match(segments[i + 1].text):
                is_end = False

        if is_end or i == len(segments) - 1:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return groups
