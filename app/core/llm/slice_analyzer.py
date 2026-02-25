"""LLM-driven video slice analyzer."""

import json
from typing import List, Tuple

import json_repair
from openai import OpenAI

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

    try:
        from app.common.config import cfg as _cfg
        client = OpenAI(
            base_url=_cfg.deepseek_api_base.value, api_key=_cfg.deepseek_api_key.value
        )
    except Exception:
        client = None

    if client is None:
        raise RuntimeError("analyze_slices requires GUI config. Use analyze_slices_cli() for CLI use.")

    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.3
    )
    content = response.choices[0].message.content.strip()

    ranges = json_repair.loads(_strip_code_fence(content))
    return _validate_ranges(ranges, len(asr_data.segments))


def analyze_slices_cli(
    asr_data: ASRData,
    model: str,
    topic: str = "science, future, AI, space, humanity, technology",
    count: int = 5,
) -> List[Tuple[int, int]]:
    """CLI-compatible slice analyzer — uses call_llm() with env-based credentials.

    Args:
        asr_data: Processed subtitle segments.
        model:    LLM model name (e.g. "deepseek-chat").
        topic:    Natural language description of what to extract.
        count:    Approximate number of clips to return.

    Returns:
        List of (start_idx, end_idx) segment index pairs.
    """
    from app.core.llm import call_llm

    if not asr_data.segments:
        return []

    subtitle_text = "\n".join(
        f"{i}: {seg.text}" for i, seg in enumerate(asr_data.segments)
    )

    prompt = (
        f"Analyze the following subtitles and identify {count} to {count + 3} segments "
        f"that contain in-depth discussion about: {topic}. "
        f"Exclude small talk, introductions, and off-topic conversation.\n\n"
        f"Subtitles:\n{subtitle_text}\n\n"
        f"Return ONLY a JSON array of [start, end] index pairs. "
        f"Example: [[0, 15], [28, 45], [60, 80]]"
    )

    response = call_llm(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.3,
    )
    content = response.choices[0].message.content.strip()
    ranges = json_repair.loads(_strip_code_fence(content))
    return _validate_ranges(ranges, len(asr_data.segments))


def _strip_code_fence(content: str) -> str:
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1]
        if content.startswith("json"):
            content = content[4:]
    return content.strip()


def _validate_ranges(ranges: object, n_segs: int) -> List[Tuple[int, int]]:
    if not isinstance(ranges, list):
        return []
    valid: List[Tuple[int, int]] = []
    for r in ranges:
        if isinstance(r, list) and len(r) == 2:
            start, end = r
            if isinstance(start, int) and isinstance(end, int):
                if 0 <= start < end < n_segs:
                    valid.append((start, end))
    return valid
