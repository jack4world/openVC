"""LLM-driven video slice analyzer."""

import json
from typing import List, Tuple

from openai import OpenAI

from app.common.config import cfg
from app.core.asr.asr_data import ASRData


def analyze_slices(asr_data: ASRData, model: str) -> List[Tuple[int, int]]:
    """Analyze subtitle content to determine video slice points.

    Args:
        asr_data: ASR data with subtitle segments
        model: LLM model name

    Returns:
        List of segment indices where slices should occur
    """
    if not asr_data.segments:
        return []

    # Build subtitle text with indices
    subtitle_text = "\n".join(
        f"{i}: {seg.text}" for i, seg in enumerate(asr_data.segments)
    )

    prompt = f"""Analyze the following subtitles and extract 5-8 segments related to: science, future, AI, space, humanity, technology. Each segment should contain in-depth discussion on these topics - NOT casual conversation.

Subtitles:
{subtitle_text}

Return ONLY a JSON array of [start, end] pairs for 5-8 segments about science/future/AI/space/humanity/technology. Example: [[0, 15], [28, 45], [60, 80]]"""

    client = OpenAI(
        base_url=cfg.deepseek_api_base.value, api_key=cfg.deepseek_api_key.value
    )
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.3
    )
    content = response.choices[0].message.content.strip()

    # Extract JSON array
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    ranges = json.loads(content)
    # 验证并返回有效范围
    valid_ranges = []
    for r in ranges:
        if isinstance(r, list) and len(r) == 2:
            start, end = r
            if 0 <= start < end < len(asr_data.segments):
                valid_ranges.append((start, end))
    return valid_ranges
