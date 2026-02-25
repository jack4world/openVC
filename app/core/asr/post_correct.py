import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

import json_repair

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.llm import call_llm
from app.core.utils.logger import setup_logger

logger = setup_logger("asr_post_correct")

_SYSTEM_PROMPT = """You are a transcript editor. Fix recognition errors in the following subtitles.

Rules:
- Fix homophones and common speech recognition mistakes
- Correct garbled proper nouns (names, brands, places) based on context
- Add missing punctuation within segments (do NOT add cross-segment punctuation)
- Remove repeated words caused by recognition glitches (e.g. "the the")
- Preserve the original meaning and every word — minimal changes only
- Do NOT translate, summarize, or paraphrase
- Return ONLY a JSON object: {"1": "corrected text", "2": "corrected text", ...}
"""


def post_correct_asr(
    asr_data: ASRData,
    model: str,
    batch_size: int = 20,
    thread_num: int = 4,
    glossary_hint: str = "",
    callback: Optional[Callable[[int, str], None]] = None,
) -> ASRData:
    segments = asr_data.segments
    total = len(segments)
    if total == 0:
        return asr_data

    batches: List[Dict[str, str]] = []
    for i in range(0, total, batch_size):
        batch = {
            str(j + 1): segments[j].text
            for j in range(i, min(i + batch_size, total))
        }
        batches.append(batch)

    system = _SYSTEM_PROMPT
    if glossary_hint:
        system += f"\n\nKnown proper nouns in this content:\n{glossary_hint}"

    corrected_map: Dict[str, str] = {}
    done_count = 0

    def correct_batch(batch: Dict[str, str]) -> Dict[str, str]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ]
        resp = call_llm(messages=messages, model=model, temperature=0.1)
        result = json_repair.loads(resp.choices[0].message.content)
        if not isinstance(result, dict):
            logger.warning("Post-correction returned non-dict, keeping originals")
            return batch
        if set(result.keys()) != set(batch.keys()):
            logger.warning("Post-correction key mismatch, keeping originals")
            return batch
        return {k: str(v) for k, v in result.items()}

    with ThreadPoolExecutor(max_workers=thread_num) as pool:
        futures = {pool.submit(correct_batch, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                result = fut.result()
                corrected_map.update(result)
            except Exception as e:
                logger.error(f"Post-correction batch failed: {e}")
                corrected_map.update(futures[fut])
            done_count += batch_size
            if callback:
                callback(min(100, int(done_count / total * 100)), "post-correcting")

    new_segments: List[ASRDataSeg] = []
    for i, seg in enumerate(segments, 1):
        corrected_text = corrected_map.get(str(i), seg.text)
        new_segments.append(ASRDataSeg(
            text=corrected_text,
            start_time=seg.start_time,
            end_time=seg.end_time,
            translated_text=seg.translated_text,
        ))

    return ASRData(new_segments)
