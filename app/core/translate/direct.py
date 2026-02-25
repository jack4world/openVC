"""Direct LLM translation — batched subtitle translation via call_llm().

Bypasses TranslatorFactory/BaseTranslator. Translates the split subtitle
segments directly using the existing LLM client and translate/standard prompt.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

import json_repair

from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.llm import call_llm
from app.core.prompts import get_prompt
from app.core.translate.types import TargetLanguage
from app.core.utils.logger import setup_logger

logger = setup_logger("direct_translate")


def translate_subtitle_with_llm(
    asr_data: ASRData,
    target_language: TargetLanguage,
    model: str,
    batch_size: int = 10,
    thread_num: int = 4,
    glossary_hint: str = "",
    callback: Optional[Callable[[int, str], None]] = None,
) -> ASRData:
    """Translate split subtitle segments directly via LLM.

    Args:
        asr_data:        Split ASRData (post-split, not raw ASR output).
        target_language: Target TargetLanguage enum value.
        model:           LLM model name.
        batch_size:      Segments per LLM call.
        thread_num:      Parallel worker threads.
        glossary_hint:   Optional extra instructions injected into system prompt.
        callback:        Optional progress callback(pct, message).
    Returns:
        New ASRData with translated_text set on each segment.
    """
    segments = list(asr_data.segments)
    if not segments:
        return asr_data

    system_prompt = get_prompt(
        "translate/standard",
        target_language=target_language.value,
        custom_prompt=glossary_hint,
    )

    batches: List[List[ASRDataSeg]] = []
    for i in range(0, len(segments), batch_size):
        batches.append(segments[i: i + batch_size])

    translated: Dict[int, str] = {}
    total = len(batches)
    done = 0

    def _translate_batch(batch_idx: int, batch: List[ASRDataSeg]) -> Dict[int, str]:
        seg_dict = {str(i): seg.text for i, seg in enumerate(batch)}
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(seg_dict, ensure_ascii=False)},
        ]
        try:
            response = call_llm(messages=messages, model=model)
            content = response.choices[0].message.content.strip()
            result: Dict[str, str] = json_repair.loads(content)
            if not isinstance(result, dict):
                raise ValueError(f"Expected dict, got {type(result)}")
            return {
                batch_idx * batch_size + int(k): str(v)
                for k, v in result.items()
                if k.isdigit()
            }
        except Exception as e:
            logger.warning(f"Batch {batch_idx} translation failed: {e}, using originals")
            return {batch_idx * batch_size + i: seg.text for i, seg in enumerate(batch)}

    with ThreadPoolExecutor(max_workers=thread_num) as executor:
        futures = {
            executor.submit(_translate_batch, idx, batch): idx
            for idx, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            translated.update(future.result())
            done += 1
            if callback:
                callback(int(done / total * 100), f"Translating batch {done}/{total}")

    new_segments: List[ASRDataSeg] = []
    for i, seg in enumerate(segments):
        new_segments.append(ASRDataSeg(
            text=seg.text,
            start_time=seg.start_time,
            end_time=seg.end_time,
            translated_text=translated.get(i, seg.text),
        ))

    return ASRData(new_segments)
