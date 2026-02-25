import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


class Glossary:
    def __init__(self, terms: Dict[str, str]):
        self.terms = terms
        self._patterns = {
            term: re.compile(re.escape(term), re.IGNORECASE)
            for term in terms
        }

    @classmethod
    def from_file(cls, path: Path) -> "Glossary":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "Glossary":
        return cls(d)

    @classmethod
    def empty(cls) -> "Glossary":
        return cls({})

    def detect_terms_in_text(self, text: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        for term, pattern in self._patterns.items():
            if pattern.search(text):
                found.append((term, self.terms[term]))
        return found

    def build_prompt_injection(self, text: str) -> str:
        found = self.detect_terms_in_text(text)
        if not found:
            return ""
        lines = ["### Terminology (MUST use these exact translations):"]
        for source, target in found:
            lines.append(f'  "{source}" → "{target}"')
        return "\n".join(lines)

    def enforce_translations(self, original: str, translated: str) -> str:
        for term, translation in self.terms.items():
            pattern = self._patterns[term]
            if pattern.search(original) and not re.search(
                re.escape(translation), translated, re.IGNORECASE
            ):
                translated = pattern.sub(translation, translated)
        return translated

    def is_empty(self) -> bool:
        return len(self.terms) == 0

    def learn_from_results(
        self,
        source_segments: List[str],
        translated_segments: List[str],
        min_occurrences: int = 3,
    ) -> Dict[str, str]:
        if len(source_segments) != len(translated_segments):
            return {}

        # Extract candidate terms: capitalized multi-word phrases and CJK-adjacent Latin
        _candidate_re = re.compile(
            r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b'  # multi-word caps: "Neural Network"
            r'|([A-Z]{2,})\b'                                 # acronyms: "GPT", "API"
        )

        term_source_counts: Dict[str, int] = {}
        term_target_renderings: Dict[str, List[str]] = {}

        for src, tgt in zip(source_segments, translated_segments):
            for m in _candidate_re.finditer(src):
                term = (m.group(1) or m.group(2)).strip()
                if not term or term in self.terms:
                    continue
                term_source_counts[term] = term_source_counts.get(term, 0) + 1
                # Find corresponding rendering in translation
                term_pat = re.compile(re.escape(term), re.IGNORECASE)
                tgt_match = term_pat.search(tgt)
                if tgt_match:
                    rendering = tgt_match.group(0)
                else:
                    # Look for immediately surrounding chars in target
                    rendering = term
                if term not in term_target_renderings:
                    term_target_renderings[term] = []
                term_target_renderings[term].append(rendering)

        newly_learned: Dict[str, str] = {}
        for term, count in term_source_counts.items():
            if count < min_occurrences:
                continue
            renderings = term_target_renderings.get(term, [])
            if not renderings:
                continue
            # Consistency check: same rendering >= 80% of occurrences
            most_common = max(set(renderings), key=renderings.count)
            if renderings.count(most_common) / len(renderings) >= 0.8:
                newly_learned[term] = most_common

        self.terms.update(newly_learned)
        for term in newly_learned:
            self._patterns[term] = re.compile(re.escape(term), re.IGNORECASE)

        return newly_learned

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.terms, f, ensure_ascii=False, indent=2)
