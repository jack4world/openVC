"""CLI Skills — OpenAI-compatible tool schemas for agent subprocess integration.

Agents use these schemas to understand available CLI tools.
Execution = subprocess call to openvc with --json-output --no-hitl.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List


PROCESS_VIDEO_SKILL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "process_video",
        "description": (
            "Transcribe, translate, and caption a video file or URL. "
            "Returns paths to the output subtitle file and optionally a captioned video."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Path to video/audio file or a URL (YouTube, etc.)"
                },
                "output_dir": {"type": "string", "description": "Output directory"},
                "transcribe_model": {
                    "type": "string",
                    "enum": ["bijian", "jianying", "whisper-api", "faster-whisper"],
                    "default": "bijian"
                },
                "source_language": {"type": "string", "default": "en"},
                "translate_to": {
                    "type": "string",
                    "description": "Target language code (zh, en, ja...). Omit to skip translation."
                },
                "glossary": {
                    "type": "object",
                    "description": "Custom terminology map {source_term: target_translation}",
                    "additionalProperties": {"type": "string"}
                },
                "optimize": {"type": "boolean", "default": False},
                "generate_video": {"type": "boolean", "default": True},
                "subtitle_layout": {
                    "type": "string",
                    "enum": ["translate-on-top", "original-on-top", "only-original", "only-translate"],
                    "default": "translate-on-top"
                },
                "style": {
                    "type": "string",
                    "enum": ["default", "highlight-bg", "minimal", "terminal-dark",
                             "documentary", "social-media"],
                    "default": "default"
                },
                "retain_metadata": {
                    "type": "boolean",
                    "description": "Preserve source video metadata in output",
                    "default": False
                },
                "llm_model": {"type": "string", "default": "gpt-4o-mini"}
            },
            "required": ["input"]
        }
    }
}

TRANSCRIBE_SKILL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "transcribe_audio",
        "description": "Transcribe audio/video to subtitle text. Returns SRT file path.",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "language": {"type": "string", "default": "en"},
                "model": {
                    "type": "string",
                    "enum": ["bijian", "jianying", "whisper-api"],
                    "default": "bijian"
                },
                "output": {"type": "string", "description": "Output SRT file path"}
            },
            "required": ["input"]
        }
    }
}

TRIM_VIDEO_SKILL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "trim_video_at_subtitles",
        "description": (
            "Extract video clips at subtitle segment boundaries. "
            "Useful for highlight reels or splitting long videos by topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "video": {"type": "string"},
                "subtitle": {"type": "string", "description": "SRT/ASS subtitle file"},
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "description": "List of [start_segment_index, end_segment_index]"
                },
                "output_dir": {"type": "string"},
                "context_secs": {"type": "number", "default": 0.5}
            },
            "required": ["video", "subtitle", "segments"]
        }
    }
}

ALL_SKILLS: List[Dict[str, Any]] = [PROCESS_VIDEO_SKILL, TRANSCRIBE_SKILL, TRIM_VIDEO_SKILL]


class SkillExecutor:
    """Execute CLI skills as subprocesses. Used by agent integrations.

    Calls the `openvc` command directly (installed as a script), with
    --json-output and --no-hitl for non-interactive agent use.
    """

    def __init__(self, openvc_cmd: str = "openvc"):
        self.openvc_cmd = openvc_cmd

    def execute(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if skill_name == "process_video":
            return self._run_process(params)
        elif skill_name == "transcribe_audio":
            return self._run_transcribe(params)
        elif skill_name == "trim_video_at_subtitles":
            return self._run_trim(params)
        raise ValueError(f"Unknown skill: {skill_name}")

    def _run_process(self, p: Dict[str, Any]) -> Dict[str, Any]:
        cmd = [
            self.openvc_cmd, "process", p["input"],
            "--model", p.get("transcribe_model", "bijian"),
            "--language", p.get("source_language", "en"),
            "--llm-model", p.get("llm_model", "gpt-4o-mini"),
            "--style", p.get("style", "default"),
            "--json-output", "--no-hitl",
        ]
        if p.get("output_dir"):
            cmd += ["--output", p["output_dir"]]
        if p.get("translate_to"):
            cmd += ["--translate", p["translate_to"]]
        if p.get("optimize"):
            cmd.append("--optimize")
        if not p.get("generate_video", True):
            cmd.append("--no-video")
        if p.get("retain_metadata"):
            cmd.append("--retain-metadata")

        glossary_path: str = ""
        if p.get("glossary"):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                            delete=False, encoding="utf-8") as f:
                json.dump(p["glossary"], f, ensure_ascii=False)
                glossary_path = f.name
            cmd += ["--glossary", glossary_path]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                return {"error": result.stderr}
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        finally:
            if glossary_path:
                Path(glossary_path).unlink(missing_ok=True)

    def _run_transcribe(self, p: Dict[str, Any]) -> Dict[str, Any]:
        cmd = [
            self.openvc_cmd, "transcribe", p["input"],
            "--model", p.get("model", "bijian"),
            "--language", p.get("language", "en"),
            "--json-output",
        ]
        if p.get("output"):
            cmd += ["--output", p["output"]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            return {"error": result.stderr}
        return json.loads(result.stdout)

    def _run_trim(self, p: Dict[str, Any]) -> Dict[str, Any]:
        segments_str = [f"{s[0]},{s[1]}" for s in p["segments"]]
        cmd = [
            self.openvc_cmd, "trim", p["video"],
            "--subtitle", p["subtitle"],
            "--segments", *segments_str,
            "--json-output",
        ]
        if p.get("output_dir"):
            cmd += ["--output-dir", p["output_dir"]]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            return {"error": result.stderr}
        return json.loads(result.stdout)
