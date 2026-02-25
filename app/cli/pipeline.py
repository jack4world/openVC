"""CLI Pipeline orchestrator — coordinates all processing stages."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.cli.config_loader import CLIConfig
from app.cli.hitl import HITLManager
from app.cli.output import ProgressReporter
from app.core.asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import (
    SubtitleLayoutEnum,
    TranscribeConfig,
    TranscribeModelEnum,
    VideoQualityEnum,
)
from app.core.translate.types import TargetLanguage

_MODEL_MAP: Dict[str, TranscribeModelEnum] = {
    "bijian": TranscribeModelEnum.BIJIAN,
    "jianying": TranscribeModelEnum.JIANYING,
    "whisper-api": TranscribeModelEnum.WHISPER_API,
    "faster-whisper": TranscribeModelEnum.FASTER_WHISPER,
    "whisper-cpp": TranscribeModelEnum.WHISPER_CPP,
}

_LAYOUT_MAP: Dict[str, SubtitleLayoutEnum] = {
    "translate-on-top": SubtitleLayoutEnum.TRANSLATE_ON_TOP,
    "original-on-top": SubtitleLayoutEnum.ORIGINAL_ON_TOP,
    "only-original": SubtitleLayoutEnum.ONLY_ORIGINAL,
    "only-translate": SubtitleLayoutEnum.ONLY_TRANSLATE,
}

_QUALITY_MAP: Dict[str, VideoQualityEnum] = {
    "ultra-high": VideoQualityEnum.ULTRA_HIGH,
    "high": VideoQualityEnum.HIGH,
    "medium": VideoQualityEnum.MEDIUM,
    "low": VideoQualityEnum.LOW,
}

_LANG_MAP: Dict[str, TargetLanguage] = {
    "zh": TargetLanguage.SIMPLIFIED_CHINESE,
    "zh-tw": TargetLanguage.TRADITIONAL_CHINESE,
    "en": TargetLanguage.ENGLISH,
    "en-us": TargetLanguage.ENGLISH_US,
    "en-uk": TargetLanguage.ENGLISH_UK,
    "ja": TargetLanguage.JAPANESE,
    "ko": TargetLanguage.KOREAN,
    "yue": TargetLanguage.CANTONESE,
    "th": TargetLanguage.THAI,
    "vi": TargetLanguage.VIETNAMESE,
    "id": TargetLanguage.INDONESIAN,
    "ms": TargetLanguage.MALAY,
    "tl": TargetLanguage.TAGALOG,
    "fr": TargetLanguage.FRENCH,
    "de": TargetLanguage.GERMAN,
    "es": TargetLanguage.SPANISH,
    "ru": TargetLanguage.RUSSIAN,
    "pt": TargetLanguage.PORTUGUESE,
    "pt-br": TargetLanguage.PORTUGUESE_BR,
    "pt-pt": TargetLanguage.PORTUGUESE_PT,
    "it": TargetLanguage.ITALIAN,
    "nl": TargetLanguage.DUTCH,
    "pl": TargetLanguage.POLISH,
    "tr": TargetLanguage.TURKISH,
    "el": TargetLanguage.GREEK,
    "cs": TargetLanguage.CZECH,
    "sv": TargetLanguage.SWEDISH,
    "da": TargetLanguage.DANISH,
    "fi": TargetLanguage.FINNISH,
    "no": TargetLanguage.NORWEGIAN,
    "hu": TargetLanguage.HUNGARIAN,
    "ro": TargetLanguage.ROMANIAN,
    "bg": TargetLanguage.BULGARIAN,
    "uk": TargetLanguage.UKRAINIAN,
    "ar": TargetLanguage.ARABIC,
    "he": TargetLanguage.HEBREW,
    "fa": TargetLanguage.PERSIAN,
}


class Pipeline:
    def __init__(self, config: CLIConfig, json_output: bool = False, hitl: bool = True):
        self.cfg = config
        self.reporter = ProgressReporter(json_output)
        self.hitl_mgr = HITLManager(
            enabled=hitl and not json_output,
            reporter=self.reporter,
        )
        self._json_output = json_output

    def run(self, args: Any) -> Dict[str, Any]:
        command: str = getattr(args, "command", "")
        if command == "process":
            return self._run_full(args)
        if command == "transcribe":
            return self._run_transcribe(args)
        if command == "subtitle":
            return self._run_subtitle(args)
        if command == "trim":
            return self._run_trim(args)
        if command == "burn":
            return self._run_burn(args)
        if command == "slice":
            return self._run_slice(args)
        raise ValueError(f"Unknown command: {command}")

    def _run_full(self, args: Any) -> Dict[str, Any]:
        self._set_llm_env()

        # Keep raw string to preserve URL scheme (Path() collapses https:// → https:/)
        input_str: str = str(args.input)
        output_dir: Path = args.output
        output_dir.mkdir(parents=True, exist_ok=True)
        no_video: bool = getattr(args, "no_video", False)

        # Step 1: For URLs, try yt-dlp transcript FIRST (no full download needed)
        asr_data: Optional[ASRData] = None
        input_path: Optional[Path] = None
        stem: str = "output"

        if self._is_url(input_str):
            self.reporter.stage("Fetching transcript (yt-dlp)")
            asr_data = self._try_ytdlp_transcript(input_str, self.cfg.transcribe_language, output_dir)
            if asr_data is not None:
                self.reporter.substage(f"Using downloaded transcript ({len(asr_data.segments)} segments)")
                # Derive a stem from the first subtitle file found in output_dir
                for ext in ("vtt", "srt", "ass"):
                    found = list(output_dir.glob(f"*.{ext}"))
                    if found:
                        stem = found[0].stem.split(".")[0].strip()[:80] or "output"
                        break

            # Download video (needed for audio extraction or video synthesis)
            if input_path is None and (asr_data is None or not no_video):
                self.reporter.stage("Downloading video")
                input_path, _ = self._ytdlp_download_video(input_str, output_dir)
                stem = input_path.stem
        else:
            input_path = Path(input_str)
            stem = input_path.stem

        source_meta = None
        if self.cfg.retain_metadata and input_path is not None:
            from app.core.metadata.extractor import extract_video_metadata
            self.reporter.stage("Extracting metadata")
            source_meta = extract_video_metadata(str(input_path))
            self.reporter.substage(f"Title: {source_meta.title or stem}")

        # Step 2: ASR (only if no transcript yet and we have a local file)
        audio_path: Optional[Path] = None
        if asr_data is None:
            if input_path is None:
                raise RuntimeError("No local video file available and no transcript obtained")
            self.reporter.stage("Extracting audio")
            from app.core.utils.video_utils import video2audio
            audio_path = output_dir / f"{stem}.mp3"
            video2audio(str(input_path), str(audio_path))

            self.reporter.stage("Transcribing")
            from app.core.asr.transcribe import transcribe
            tcfg = self._build_transcribe_config()
            asr_data = transcribe(str(audio_path), tcfg, callback=self.reporter.asr_callback)

        if self.cfg.post_correct:
            if self._has_llm_key():
                from app.core.asr.post_correct import post_correct_asr
                self.reporter.substage("Post-correcting transcript")
                glossary_hint = "\n".join(self.cfg.glossary.keys()) if self.cfg.glossary else ""
                asr_data = post_correct_asr(
                    asr_data,
                    model=self.cfg.llm_model,
                    glossary_hint=glossary_hint,
                    callback=self.reporter.asr_callback,
                )
            else:
                self.reporter.substage("Skipping post-correction (no API key)")

        raw_srt = output_dir / f"[raw]{stem}.srt"
        asr_data.save(str(raw_srt))

        asr_data = self.hitl_mgr.checkpoint_transcript(asr_data, raw_srt)

        self.reporter.stage("Processing subtitles")
        processed = self._process_subtitles(asr_data)

        if self.cfg.sync_check and audio_path is not None:
            from app.core.sync.drift_detector import detect_and_correct_drift
            self.reporter.substage("Checking audio-subtitle drift")
            processed, drift_reports = detect_and_correct_drift(processed, str(audio_path))
            if drift_reports:
                self.reporter.substage(f"Drift: {len(drift_reports)} samples checked")

        processed = self.hitl_mgr.checkpoint_subtitle(processed)

        style_from_flag = getattr(args, "style", "default") != "default"
        selected_style = self.hitl_mgr.checkpoint_style(
            self.cfg.subtitle_style,
            style_from_flag=style_from_flag,
        )

        layout = _LAYOUT_MAP.get(self.cfg.subtitle_layout, SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        from app.core.utils.get_subtitle_style import get_subtitle_style
        ass_style = get_subtitle_style(selected_style)

        processed_ass = output_dir / f"[styled]{stem}.ass"
        processed.save(str(processed_ass), ass_style=ass_style, layout=layout)

        result_files: Dict[str, Any] = {
            "subtitle": str(processed_ass.resolve()),
            "raw_transcript": str(raw_srt.resolve()),
        }

        if not getattr(args, "no_video", False):
            self.reporter.stage("Synthesizing video")
            from app.core.utils.video_utils import add_subtitles
            output_video = output_dir / f"[captioned]{stem}.mp4"
            quality = _QUALITY_MAP.get(getattr(args, "quality", "medium"), VideoQualityEnum.MEDIUM)
            add_subtitles(
                str(input_path), str(processed_ass), str(output_video),
                crf=quality.get_crf(),
                preset=quality.get_preset(),
                soft_subtitle=getattr(args, "soft_subtitle", False),
                progress_callback=lambda v, m: self.reporter.progress(int(float(v or 0)), m),
            )
            result_files["video"] = str(output_video.resolve())

            if self.cfg.retain_metadata and source_meta is not None:
                from app.core.metadata.extractor import embed_metadata_in_video, write_sidecar_json
                meta_out = output_dir / f"{stem}.meta.json"
                embed_metadata_in_video(str(output_video), source_meta, processed)
                write_sidecar_json(meta_out, source_meta, processed)
                result_files["metadata"] = str(meta_out.resolve())

        # Optional: reframe captioned video to portrait (TikTok/Reels/Shorts)
        if self.cfg.reframe_after and "video" in result_files:
            self.reporter.stage(f"Reframing to portrait ({self.cfg.reframe_mode})")
            from app.core.video.reframe import reframe_video
            src_video = result_files["video"]
            portrait_path = str(output_dir / f"[vertical]{stem}.mp4")
            try:
                reframe_video(
                    input_path=src_video,
                    output_path=portrait_path,
                    mode=self.cfg.reframe_mode,
                    width=self.cfg.reframe_width,
                    height=self.cfg.reframe_height,
                    blur_strength=self.cfg.reframe_blur,
                    quality=self.cfg.video_quality,
                    subtitle_file=None,  # subtitles already burned into src_video
                )
                result_files["vertical_video"] = portrait_path
                self.reporter.substage(f"Portrait video → {portrait_path}")
            except Exception as exc:
                self.reporter.substage(f"Reframe failed: {exc}")

        # Optional: LLM-driven semantic slicing after full processing
        if self.cfg.slice_after and self._has_llm_key():
            slice_output_dir = self.cfg.slice_dir or (output_dir / "slices")
            self.reporter.stage(f"Slicing into semantic clips (topic: {self.cfg.slice_topic!r})")
            try:
                from app.core.llm.slice_analyzer import analyze_slices_cli
                from app.core.split.trim import export_clip_subtitles, trim_at_subtitle_boundaries
                ranges = analyze_slices_cli(
                    processed,
                    model=self.cfg.llm_model,
                    topic=self.cfg.slice_topic,
                    count=self.cfg.slice_count,
                )
                self.reporter.substage(f"LLM identified {len(ranges)} segments")
                clip_paths = trim_at_subtitle_boundaries(
                    str(input_path) if input_path else result_files.get("video", ""),
                    processed,
                    ranges,
                    str(slice_output_dir),
                    context_secs=self.cfg.slice_context_secs,
                )
                sub_paths = export_clip_subtitles(
                    processed,
                    ranges,
                    str(slice_output_dir),
                    context_secs=self.cfg.slice_context_secs,
                    ass_style=ass_style,
                )
                result_files["clips"] = clip_paths
                result_files["clip_subtitles"] = sub_paths
                self.reporter.substage(f"Saved {len(clip_paths)} clips → {slice_output_dir}")
            except Exception as exc:
                self.reporter.substage(f"Slicing failed: {exc}")
        elif self.cfg.slice_after:
            self.reporter.substage("Skipping slice (no LLM API key)")

        self.reporter.done("Pipeline complete")
        stats = self._build_stats(asr_data, processed)
        self.reporter.print_completion_summary(
            result_files,
            stats,
            json_output=self._json_output,
        )
        if self._json_output:
            result_files["stats"] = stats
        return result_files

    def _run_transcribe(self, args: Any) -> Dict[str, Any]:
        self._set_llm_env()
        input_path = Path(str(args.input))
        output: Optional[Path] = getattr(args, "output", None)

        self.reporter.stage("Transcribing")

        from app.core.utils.video_utils import video2audio
        audio_extensions = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus"}
        if input_path.suffix.lower() not in audio_extensions:
            audio_path = input_path.with_suffix(".mp3")
            video2audio(str(input_path), str(audio_path))
        else:
            audio_path = input_path

        from app.core.asr.transcribe import transcribe
        tcfg = self._build_transcribe_config()
        asr_data = transcribe(str(audio_path), tcfg, callback=self.reporter.asr_callback)

        fmt: str = getattr(args, "format", "srt")
        if output is None:
            output = input_path.with_suffix(f".{fmt}")

        asr_data.save(str(output))
        self.reporter.done("Transcription complete")
        return {"output": str(output.resolve()), "segments": len(asr_data.segments)}

    def _run_subtitle(self, args: Any) -> Dict[str, Any]:
        self._set_llm_env()
        input_path = Path(str(args.input))
        output: Optional[Path] = getattr(args, "output", None)

        self.reporter.stage("Loading subtitle")
        asr_data = ASRData.from_subtitle_file(str(input_path))

        self.reporter.stage("Processing subtitles")
        processed = self._process_subtitles(asr_data)

        if output is None:
            output = input_path.with_stem(f"[processed]{input_path.stem}")

        layout = _LAYOUT_MAP.get(self.cfg.subtitle_layout, SubtitleLayoutEnum.TRANSLATE_ON_TOP)
        from app.core.utils.get_subtitle_style import get_subtitle_style
        ass_style = get_subtitle_style(self.cfg.subtitle_style)
        processed.save(str(output), ass_style=ass_style, layout=layout)

        result_files: Dict[str, Any] = {"subtitle": str(output.resolve())}

        video: Optional[Path] = getattr(args, "video", None)
        if video is not None:
            self.reporter.stage("Synthesizing video")
            from app.core.utils.video_utils import add_subtitles
            output_video = video.with_stem(f"[captioned]{video.stem}")
            add_subtitles(
                str(video), str(output), str(output_video),
                progress_callback=lambda v, m: self.reporter.progress(int(float(v or 0)), m),
            )
            result_files["video"] = str(output_video.resolve())

        self.reporter.done("Subtitle processing complete")
        return result_files

    def _run_burn(self, args: Any) -> Dict[str, Any]:
        """Burn an existing subtitle file into a video — no subtitle reprocessing."""
        video_path = Path(str(args.video))
        subtitle_path = Path(str(args.subtitle))
        output: Optional[Path] = getattr(args, "output", None)
        soft: bool = getattr(args, "soft", False)

        if output is None:
            output = video_path.with_stem(f"[captioned]{video_path.stem}")

        quality = _QUALITY_MAP.get(getattr(args, "quality", "medium"), VideoQualityEnum.MEDIUM)

        self.reporter.stage("Burning subtitle into video")
        from app.core.utils.video_utils import add_subtitles
        add_subtitles(
            str(video_path),
            str(subtitle_path),
            str(output),
            crf=quality.get_crf(),
            preset=quality.get_preset(),
            soft_subtitle=soft,
            progress_callback=lambda v, m: self.reporter.progress(int(float(v or 0)), m),
        )
        self.reporter.done(f"Done: {output}")
        return {"video": str(output.resolve())}

    def _run_trim(self, args: Any) -> Dict[str, Any]:
        video_path = Path(str(args.video))
        subtitle_path = Path(str(args.subtitle))
        output_dir: Path = getattr(args, "output_dir", Path("./clips"))
        context_secs: float = getattr(args, "context_secs", 0.5)

        asr_data = ASRData.from_subtitle_file(str(subtitle_path))

        segment_ranges: List[Tuple[int, int]] = []
        for seg_str in (getattr(args, "segments", None) or []):
            parts = seg_str.split(",")
            if len(parts) == 2:
                segment_ranges.append((int(parts[0]), int(parts[1])))

        from app.core.split.trim import trim_at_subtitle_boundaries
        clip_paths = trim_at_subtitle_boundaries(
            str(video_path), asr_data, segment_ranges, str(output_dir), context_secs
        )
        return {"clips": clip_paths}

    def _run_slice(self, args: Any) -> Dict[str, Any]:
        self._set_llm_env()

        video_path = Path(str(args.video))
        subtitle_path = Path(str(args.subtitle))
        output_dir: Path = getattr(args, "output_dir", Path("./slices"))
        context_secs: float = getattr(args, "context_secs", 1.0)
        topic: str = getattr(args, "topic", None) or "the most informative and substantive discussion segments"
        count: int = getattr(args, "count", 5)
        export_subs: bool = not getattr(args, "no_subtitle_export", False)

        self.reporter.stage("Loading subtitle")
        asr_data = ASRData.from_subtitle_file(str(subtitle_path))
        self.reporter.substage(f"{len(asr_data.segments)} segments loaded")

        self.reporter.stage("Analyzing segments with LLM")
        from app.core.llm.slice_analyzer import analyze_slices_cli
        slice_ranges = analyze_slices_cli(
            asr_data,
            model=self.cfg.llm_model,
            topic=topic,
            count=count,
        )

        if not slice_ranges:
            self.reporter.substage("No segments identified — try a different --topic")
            return {"clips": [], "subtitles": []}

        self.reporter.substage(f"{len(slice_ranges)} segments identified")
        for i, (s, e) in enumerate(slice_ranges):
            start_ts = asr_data.segments[s].start_time
            end_ts = asr_data.segments[e].end_time
            m_s, sec_s = divmod(start_ts // 1000, 60)
            m_e, sec_e = divmod(end_ts // 1000, 60)
            preview = asr_data.segments[s].text[:60]
            self.reporter.substage(
                f"  Clip {i+1}: [{m_s:02d}:{sec_s:02d} → {m_e:02d}:{sec_e:02d}]  {preview}…"
            )

        self.reporter.stage("Exporting video clips")
        from app.core.split.trim import trim_at_subtitle_boundaries, export_clip_subtitles
        clip_paths = trim_at_subtitle_boundaries(
            str(video_path), asr_data, slice_ranges, str(output_dir), context_secs
        )

        sub_paths: List[str] = []
        if export_subs:
            self.reporter.substage("Exporting per-clip subtitles")
            from app.core.utils.get_subtitle_style import get_subtitle_style
            ass_style = get_subtitle_style(self.cfg.subtitle_style)
            sub_paths = export_clip_subtitles(
                asr_data, slice_ranges, str(output_dir), context_secs, ass_style
            )

        self.reporter.done(f"Slicing complete — {len(clip_paths)} clips saved to {output_dir}")
        return {"clips": clip_paths, "subtitles": sub_paths}

    def _is_word_level(self, asr_data: ASRData) -> bool:
        segs = asr_data.segments
        if not segs:
            return False
        avg_words = sum(len(s.text.split()) for s in segs) / len(segs)
        return avg_words < 2.5

    def _process_subtitles(self, asr_data: ASRData) -> ASRData:
        result = asr_data
        has_key = self._has_llm_key()

        if self.cfg.need_split:
            # Word-level input (e.g. bijian ASR) must always use rule-based split;
            # LLM splitter expects phrase-level input.
            if not self._is_word_level(result) and has_key:
                self.reporter.substage("Splitting subtitles")
                from app.core.split.split import SubtitleSplitter
                splitter = SubtitleSplitter(
                    thread_num=self.cfg.thread_num,
                    model=self.cfg.llm_model,
                    max_word_count_cjk=self.cfg.max_word_count_cjk,
                    max_word_count_english=self.cfg.max_word_count_english,
                )
                result = splitter.split_subtitle(result)
            else:
                label = "Splitting subtitles (rule-based)" if has_key else "Splitting subtitles (rule-based, no API key)"
                self.reporter.substage(label)
                result = self._rule_based_split(result)

        if self.cfg.need_optimize:
            if has_key:
                self.reporter.substage("Optimizing subtitles")
                from app.core.optimize.optimize import SubtitleOptimizer
                optimizer = SubtitleOptimizer(
                    thread_num=self.cfg.thread_num,
                    batch_num=self.cfg.batch_size,
                    model=self.cfg.llm_model,
                    custom_prompt="",
                )
                result = optimizer.optimize_subtitle_selective(result)
            else:
                self.reporter.substage("Skipping optimization (no API key)")

        if self.cfg.need_translate:
            if has_key:
                target_lang = _LANG_MAP.get(
                    self.cfg.target_language, TargetLanguage.SIMPLIFIED_CHINESE
                )
                self.reporter.substage(f"Translating to {target_lang.value}")
                from app.core.translate.direct import translate_subtitle_with_llm
                glossary_hint = "\n".join(self.cfg.glossary.keys()) if self.cfg.glossary else ""
                result = translate_subtitle_with_llm(
                    result,
                    target_language=target_lang,
                    model=self.cfg.llm_model,
                    batch_size=self.cfg.batch_size,
                    thread_num=self.cfg.thread_num,
                    glossary_hint=glossary_hint,
                    callback=self.reporter.asr_callback,
                )
                if self.cfg.glossary_learn and self.cfg.glossary_save_path:
                    from app.core.glossary import Glossary
                    glossary = (
                        Glossary.from_dict(self.cfg.glossary)
                        if self.cfg.glossary
                        else Glossary.empty()
                    )
                    source_segs = [s.text for s in asr_data.segments]
                    trans_segs = [s.translated_text or "" for s in result.segments]
                    learned = glossary.learn_from_results(source_segs, trans_segs)
                    if learned:
                        glossary.save(self.cfg.glossary_save_path)
            else:
                self.reporter.substage("Skipping translation (no API key)")

        return result

    def _set_llm_env(self) -> None:
        if self.cfg.api_key:
            os.environ["OPENAI_API_KEY"] = self.cfg.api_key
        if self.cfg.base_url:
            os.environ["OPENAI_BASE_URL"] = self.cfg.base_url

    def _has_llm_key(self) -> bool:
        return bool(self.cfg.api_key or os.environ.get("OPENAI_API_KEY"))

    def _rule_based_split(self, asr_data: ASRData) -> ASRData:
        segments = list(asr_data.segments)
        if not segments:
            return asr_data

        # Detect word-level output: average < 2 words per segment (e.g. bijian)
        avg_words = sum(len(s.text.split()) for s in segments) / len(segments)
        merged: List[ASRDataSeg] = []

        if avg_words < 2.5:
            # Word-level: group into subtitle lines by word count
            max_words = self.cfg.max_word_count_english
            i = 0
            while i < len(segments):
                group = [segments[i]]
                wc = len(segments[i].text.split())
                j = i + 1
                while j < len(segments) and wc + len(segments[j].text.split()) <= max_words:
                    wc += len(segments[j].text.split())
                    group.append(segments[j])
                    j += 1
                merged.append(ASRDataSeg(
                    text=" ".join(s.text for s in group).strip(),
                    start_time=group[0].start_time,
                    end_time=group[-1].end_time,
                ))
                i = j
        else:
            # Phrase-level: split on punctuation + time gaps
            from app.core.split.boundary import pre_segment_by_rules
            for group in pre_segment_by_rules(segments):
                if not group:
                    continue
                merged.append(ASRDataSeg(
                    text=" ".join(seg.text for seg in group).strip(),
                    start_time=group[0].start_time,
                    end_time=group[-1].end_time,
                ))

        return ASRData(merged) if merged else asr_data

    @staticmethod
    def _is_url(s: str) -> bool:
        return s.startswith("http://") or s.startswith("https://")

    def _ytdlp_download_video(self, url: str, output_dir: Path) -> Tuple[Path, Optional[Path]]:
        """Download video via yt-dlp. Returns (video_path, subtitle_path_or_None)."""
        import yt_dlp
        from app.config import APPDATA_PATH

        sub_dir = output_dir / "subtitles"
        sub_dir.mkdir(parents=True, exist_ok=True)

        ydl_opts: Dict[str, Any] = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "outtmpl": {
                "default": str(output_dir / "%(title).200s.%(ext)s"),
                "subtitle": str(sub_dir / "%(title).100s.%(ext)s"),
            },
            "writeautomaticsub": True,
            "writesubtitles": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        cookiefile = APPDATA_PATH / "cookies.txt"
        if cookiefile.exists():
            ydl_opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = Path(ydl.prepare_filename(info))

        subtitle_path: Optional[Path] = None
        for ext in ("vtt", "srt", "ass"):
            for f in sub_dir.glob(f"*.{ext}"):
                subtitle_path = f
                break
            if subtitle_path:
                break

        return video_path, subtitle_path

    def _try_ytdlp_transcript(
        self,
        input_str: str,
        language: str,
        work_dir: Path,
    ) -> Optional[ASRData]:
        """Attempt to get a transcript via yt-dlp (auto-captions).

        Works for YouTube URLs and other yt-dlp-supported sources.
        Returns None if unavailable, local file, or on any error.
        """
        if not self._is_url(input_str):
            return None

        try:
            import yt_dlp
        except ImportError:
            return None

        # Include regional variants (e.g. "en" → also tries "en-US", "en-GB", "en-IN", etc.)
        base_lang = language.split("-")[0]
        lang_variants = [language, f"{language}-orig", base_lang]

        ydl_opts: Dict[str, Any] = {
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": lang_variants,
            "outtmpl": str(work_dir / "%(title).100s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([input_str])
        except Exception as e:
            from app.core.utils.logger import setup_logger
            setup_logger("pipeline").debug(f"yt-dlp transcript attempt failed: {e}")
            return None

        # Search work_dir for any subtitle file (yt-dlp places them alongside video)
        for ext in ("vtt", "srt", "ass"):
            for f in sorted(work_dir.glob(f"*.{ext}")):
                try:
                    result = ASRData.from_subtitle_file(str(f))
                    if result.segments:
                        return result
                except Exception:
                    continue

        return None

    def _build_transcribe_config(self) -> TranscribeConfig:
        return TranscribeConfig(
            transcribe_model=_MODEL_MAP.get(self.cfg.transcribe_model, TranscribeModelEnum.BIJIAN),
            transcribe_language=self.cfg.transcribe_language,
            need_word_time_stamp=self.cfg.word_timestamps,
        )

    def _build_stats(self, original: ASRData, processed: ASRData) -> Dict[str, Any]:
        duration_ms = max(
            (s.end_time for s in original.segments), default=0
        )
        translated_count = sum(1 for s in processed.segments if s.translated_text)
        untranslated = sum(
            1 for s in processed.segments
            if s.translated_text and s.translated_text.strip() == s.text.strip()
        )
        return {
            "segments_total": len(original.segments),
            "segments_processed": len(processed.segments),
            "translations": translated_count,
            "untranslated_warnings": untranslated,
            "duration_ms": duration_ms,
            "elapsed_s": self.reporter.elapsed(),
        }
