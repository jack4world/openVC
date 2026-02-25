#!/usr/bin/env python3
"""
openVC — AI-powered video captioning pipeline.

Usage examples:
  # Full pipeline
  openvc process video.mp4 --translate zh --output ./out/

  # Transcription only
  openvc transcribe audio.mp3 --model bijian --format srt

  # Subtitle processing only (split + optimize + translate)
  openvc subtitle raw.srt --translate zh --glossary terms.json

  # Video trimming at subtitle boundaries
  openvc trim video.mp4 --subtitle processed.srt --segments 0,5 2,8

  # Agent-friendly (non-interactive, JSON output)
  openvc process video.mp4 --translate zh --json-output --no-hitl

  # First-time setup wizard (API key, model, style, language, etc.)
  openvc setup

  # CI/agent: print current config as JSON and exit
  openvc setup --non-interactive

  # Persistent config (individual key)
  openvc config set subtitle_style science-vlog
  openvc config get api_key
  openvc config list
"""

import json
import os
import sys
from pathlib import Path


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="openvc",
        description="🐦 openVC — AI Video Captioning Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=Path, help="Config JSON file path")
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON (for agent consumption)",
    )
    parser.add_argument(
        "--no-hitl",
        action="store_true",
        help="Disable human-in-the-loop checkpoints (env: OPENVC_NO_HITL=1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing any LLM/ASR/ffmpeg calls",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── agent (LLM/developer utilities) ──────────────────────────────────────
    agent_cmd = subparsers.add_parser(
        "agent", help="Helper commands for LLM agent and developer integration"
    )
    agent_sub = agent_cmd.add_subparsers(dest="agent_subcommand", required=True)

    agent_sub.add_parser(
        "exit-codes",
        help="Print stable exit codes for automation (aliases: exitcodes)",
    )
    schema_cmd = agent_sub.add_parser(
        "schema",
        help="Print CLI structure as JSON for agent discovery",
    )
    schema_cmd.add_argument(
        "schema_command",
        nargs="?",
        metavar="COMMAND",
        help="Describe a specific subcommand, e.g. 'process'",
    )

    # ── setup (interactive onboarding wizard) ─────────────────────────────────
    setup_cmd = subparsers.add_parser(
        "setup", help="Interactive setup wizard — configure all settings in one go"
    )
    setup_cmd.add_argument(
        "--non-interactive",
        action="store_true",
        help="Print current config as JSON and exit (CI/agent-friendly)",
    )

    # ── config (persistent defaults) ─────────────────────────────────────────
    cfg_cmd = subparsers.add_parser(
        "config", help="Get/set persistent defaults (~/.openvc/config.json)"
    )
    cfg_cmd.add_argument("action", choices=["set", "get", "list"])
    cfg_cmd.add_argument("key", nargs="?", help="Config key (e.g. style, layout)")
    cfg_cmd.add_argument("value", nargs="?", help="Value to set")

    # ── process (full pipeline) ──────────────────────────────────────────────
    proc = subparsers.add_parser(
        "process", help="Full pipeline: ASR → split → translate → synthesize"
    )
    proc.add_argument("input", help="Video/audio file or URL")
    proc.add_argument("--output", "-o", type=Path, default=Path("./output"))
    proc.add_argument(
        "--model",
        default="bijian",
        choices=["bijian", "jianying", "whisper-api", "faster-whisper", "whisper-cpp"],
    )
    proc.add_argument("--language", default="en", help="Source language code")
    proc.add_argument("--translate", metavar="LANG", help="Target language for translation")
    proc.add_argument("--glossary", type=Path, help="Glossary JSON file {term: translation}")
    proc.add_argument(
        "--glossary-learn",
        action="store_true",
        help="Auto-learn new terms from translation results (opt-in)",
    )
    proc.add_argument(
        "--glossary-save",
        type=Path,
        metavar="PATH",
        help="Path to persist cumulative glossary (default: ~/.openvc/glossary.json)",
    )
    proc.add_argument("--style", default="default", help="Subtitle style preset name")
    proc.add_argument(
        "--layout",
        default="translate-on-top",
        choices=["translate-on-top", "original-on-top", "only-original", "only-translate"],
    )
    proc.add_argument("--no-optimize", action="store_true")
    proc.add_argument(
        "--post-correct", action="store_true", help="Run LLM ASR post-correction (opt-in)"
    )
    proc.add_argument("--no-video", action="store_true", help="Skip video synthesis")
    proc.add_argument(
        "--quality",
        default="medium",
        choices=["ultra-high", "high", "medium", "low"],
    )
    proc.add_argument("--soft-subtitle", action="store_true")
    proc.add_argument(
        "--llm-model", default=None, help="LLM model for all AI tasks"
    )
    proc.add_argument("--base-url", default=None)
    proc.add_argument("--api-key", default=None, help="LLM API key (or set OPENAI_API_KEY env)")
    proc.add_argument(
        "--retain-metadata",
        action="store_true",
        help="Extract and embed source video metadata in output",
    )
    proc.add_argument(
        "--sync-check",
        action="store_true",
        help="Run audio-subtitle drift detection",
    )
    proc.add_argument("--max-cjk", type=int, metavar="N", help="Max CJK chars per subtitle line")
    proc.add_argument(
        "--max-en", type=int, metavar="N", help="Max English words per subtitle line"
    )
    proc.add_argument("--batch-size", type=int, metavar="N", help="LLM batch size")
    proc.add_argument("--threads", type=int, metavar="N", help="Parallel worker threads")
    proc.add_argument("--work-dir", type=Path, metavar="PATH", help="Working directory")
    proc.add_argument(
        "--translator-service",
        default="llm",
        choices=["llm", "bing", "google", "deeplx"],
        help="Translation service backend",
    )
    proc.add_argument(
        "--no-input",
        action="store_true",
        help="Never prompt for interactive input (for headless/CI use)",
    )
    proc.add_argument(
        "--slice",
        action="store_true",
        help="After full processing, auto-slice into semantic clips via LLM",
    )
    proc.add_argument(
        "--topic",
        default=None,
        help='Topic/theme to extract when slicing (default: most informative segments)',
    )
    proc.add_argument(
        "--slice-count",
        type=int,
        default=5,
        metavar="N",
        help="Approximate number of clips to extract when slicing (default: 5)",
    )
    proc.add_argument(
        "--slice-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output directory for sliced clips (default: <output>/slices/)",
    )
    proc.add_argument(
        "--context-secs",
        type=float,
        default=1.0,
        help="Extra seconds before/after each slice boundary (default: 1.0)",
    )

    # ── transcribe ───────────────────────────────────────────────────────────
    tr = subparsers.add_parser("transcribe", help="ASR only")
    tr.add_argument("input", type=Path)
    tr.add_argument("--output", "-o", type=Path)
    tr.add_argument("--model", default="bijian")
    tr.add_argument("--language", default="en")
    tr.add_argument("--format", default="srt", choices=["srt", "ass", "vtt", "txt", "json"])
    tr.add_argument("--word-timestamps", action="store_true")

    # ── subtitle ─────────────────────────────────────────────────────────────
    sub = subparsers.add_parser("subtitle", help="Subtitle processing only")
    sub.add_argument("input", type=Path, help="Existing subtitle file")
    sub.add_argument("--video", type=Path, help="Associated video (for synthesis)")
    sub.add_argument("--output", "-o", type=Path)
    sub.add_argument("--translate", metavar="LANG")
    sub.add_argument("--glossary", type=Path)
    sub.add_argument("--optimize", action="store_true")
    sub.add_argument("--llm-model", default=None)
    sub.add_argument("--base-url", default=None)
    sub.add_argument("--api-key", default=None, help="LLM API key (or set OPENAI_API_KEY env)")
    sub.add_argument("--threads", type=int, metavar="N", help="Parallel worker threads")
    sub.add_argument("--batch-size", type=int, metavar="N", help="LLM batch size")
    sub.add_argument(
        "--layout",
        default="translate-on-top",
        choices=["translate-on-top", "original-on-top", "only-original", "only-translate"],
    )

    # ── burn ─────────────────────────────────────────────────────────────────
    burn = subparsers.add_parser(
        "burn", help="Burn an existing subtitle file into a video (no reprocessing)"
    )
    burn.add_argument("video", type=Path, help="Input video file")
    burn.add_argument("--subtitle", type=Path, required=True, help="ASS/SRT subtitle file to burn in")
    burn.add_argument("--output", "-o", type=Path, default=None, help="Output video path")
    burn.add_argument(
        "--quality",
        default="medium",
        choices=["ultra-high", "high", "medium", "low"],
    )
    burn.add_argument("--soft", action="store_true", help="Soft subtitle (mux, don't burn)")

    # ── trim ─────────────────────────────────────────────────────────────────
    trim = subparsers.add_parser("trim", help="Clip video at subtitle segment boundaries")
    trim.add_argument("video", type=Path)
    trim.add_argument("--subtitle", type=Path, required=True)
    trim.add_argument(
        "--segments",
        nargs="+",
        metavar="START,END",
        help="Segment index ranges e.g. 0,10 15,30",
    )
    trim.add_argument("--output-dir", type=Path, default=Path("./clips"))
    trim.add_argument(
        "--context-secs",
        type=float,
        default=0.5,
        help="Extra seconds before/after clip boundary",
    )

    # ── slice ─────────────────────────────────────────────────────────────────
    slc = subparsers.add_parser(
        "slice",
        help="LLM-driven semantic slicing: auto-detect interesting segments and export clips",
    )
    slc.add_argument("video", type=Path, help="Video file to slice")
    slc.add_argument("--subtitle", type=Path, required=True, help="Subtitle file (SRT/ASS)")
    slc.add_argument(
        "--topic",
        default=None,
        help='What to extract (default: "the most informative and substantive discussion segments")',
    )
    slc.add_argument("--count", type=int, default=5, help="Approximate number of clips (default: 5)")
    slc.add_argument("--output-dir", type=Path, default=Path("./slices"))
    slc.add_argument(
        "--context-secs",
        type=float,
        default=1.0,
        help="Extra seconds before/after each clip boundary (default: 1.0)",
    )
    slc.add_argument("--llm-model", default=None, help="LLM model name")
    slc.add_argument("--base-url", default=None)
    slc.add_argument("--api-key", default=None)
    slc.add_argument("--no-subtitle-export", action="store_true", help="Skip exporting per-clip subtitles")

    # ── reframe ───────────────────────────────────────────────────────────────
    rf = subparsers.add_parser(
        "reframe",
        help="Convert landscape video to portrait (TikTok/Reels/Shorts) format",
    )
    rf.add_argument("video", type=Path, help="Input landscape video file")
    rf.add_argument("--output", "-o", type=Path, default=None, help="Output path (default: <input>_vertical.mp4)")
    rf.add_argument(
        "--mode",
        default="blur-bg",
        choices=["blur-bg", "crop-center", "split"],
        help=(
            "Reframe mode: "
            "blur-bg=original centred on blurred background (TikTok style, default), "
            "crop-center=centre-crop to 9:16, "
            "split=original on top / blurred zoom on bottom"
        ),
    )
    rf.add_argument("--width",  type=int, default=1080, help="Output width  (default: 1080)")
    rf.add_argument("--height", type=int, default=1920, help="Output height (default: 1920)")
    rf.add_argument(
        "--blur",
        type=int,
        default=40,
        metavar="N",
        help="Blur strength for blur-bg / split modes (default: 40)",
    )
    rf.add_argument(
        "--quality",
        default="medium",
        choices=["ultra-high", "high", "medium", "low"],
    )
    rf.add_argument(
        "--subtitle",
        type=Path,
        default=None,
        help="Optional ASS/SRT file to burn into the reframed video",
    )

    return parser


def _handle_config_command(args) -> int:
    from app.cli.config_loader import load_persistent_config, save_persistent_config

    action: str = args.action
    key: str = args.key or ""
    value: str = args.value or ""

    if action == "list":
        data = load_persistent_config()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if action == "get":
        if not key:
            print("Error: key required for 'get'", file=sys.stderr)
            return 1
        data = load_persistent_config()
        if key in data:
            print(data[key])
        else:
            print(f"(not set)", file=sys.stderr)
        return 0

    if action == "set":
        if not key or not value:
            print("Error: key and value required for 'set'", file=sys.stderr)
            return 1
        data = load_persistent_config()
        data[key] = value
        save_persistent_config(data)
        print(f"Set {key} = {value}")
        return 0

    return 1


def _handle_reframe_command(args, json_output: bool = False) -> int:
    """Run the reframe pipeline: landscape → portrait."""
    from app.core.video.reframe import reframe_video

    input_path = str(args.video.resolve())

    if args.output:
        output_path = str(args.output.resolve())
    else:
        stem = args.video.stem
        output_path = str(args.video.parent / f"{stem}_vertical.mp4")

    subtitle_file = str(args.subtitle.resolve()) if args.subtitle else None

    if not json_output:
        mode_desc = {
            "blur-bg":     "blurred background (TikTok style)",
            "crop-center": "centre-crop",
            "split":       "split-screen (original top / zoom bottom)",
        }.get(args.mode, args.mode)
        print(f"\n  Reframing → {args.mode}  ({mode_desc})", file=sys.stderr)
        print(f"  Input  : {input_path}", file=sys.stderr)
        print(f"  Output : {output_path}", file=sys.stderr)
        print(f"  Canvas : {args.width}×{args.height}", file=sys.stderr)
        if subtitle_file:
            print(f"  Subtitle: {subtitle_file}", file=sys.stderr)
        print(file=sys.stderr)

    try:
        out = reframe_video(
            input_path=input_path,
            output_path=output_path,
            mode=args.mode,
            width=args.width,
            height=args.height,
            blur_strength=args.blur,
            quality=args.quality,
            subtitle_file=subtitle_file,
        )
    except Exception as exc:
        if json_output:
            import json as _json
            print(_json.dumps({"error": str(exc), "exit_code": 1, "type": "error"}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if json_output:
        import json as _json
        print(_json.dumps({"output": out, "mode": args.mode, "width": args.width, "height": args.height}))
    else:
        size_mb = Path(out).stat().st_size / (1024 * 1024)
        print(f"  ✓ Done  →  {out}  ({size_mb:.1f} MB)", file=sys.stderr)

    return 0


def main() -> None:
    from app.cli.banner import print_banner
    from app.cli.exit_codes import (
        EXIT_CANCELLED, EXIT_ERROR,
        OpenVCError, classify_exception,
    )

    parser = _build_parser()
    args = parser.parse_args()

    # ── Env var overrides (lower precedence than explicit flags) ──────────────
    # OPENVC_JSON=1        → --json-output
    # OPENVC_NO_HITL=1     → --no-hitl
    # OPENVC_API_KEY=sk-xx → sets api_key (falls through to CLIConfig)
    if os.getenv("OPENVC_JSON") == "1" and not getattr(args, "json_output", False):
        args.json_output = True
    if os.getenv("OPENVC_NO_HITL") == "1" and not getattr(args, "no_hitl", False):
        args.no_hitl = True
    # OPENVC_API_KEY is also accepted (in addition to OPENAI_API_KEY)
    if os.getenv("OPENVC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["OPENVC_API_KEY"]

    json_output: bool = getattr(args, "json_output", False)
    no_hitl: bool = getattr(args, "no_hitl", False)
    dry_run: bool = getattr(args, "dry_run", False)

    # ── agent subcommand (no banner needed) ───────────────────────────────────
    if args.command == "agent":
        from app.cli.agent import handle_agent_command
        sys.exit(handle_agent_command(args, parser))

    if args.command == "setup":
        from app.cli.setup import run_setup
        sys.exit(run_setup(non_interactive=getattr(args, "non_interactive", False)))

    if args.command == "config":
        sys.exit(_handle_config_command(args))

    if args.command == "reframe":
        sys.exit(_handle_reframe_command(args, json_output=json_output))

    print_banner(json_output=json_output)

    # ── dry-run: describe what would happen and exit ──────────────────────────
    if dry_run:
        plan = _describe_dry_run(args)
        if json_output:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print("\n  [dry-run] Would execute:")
            for step in plan.get("steps", []):
                print(f"    • {step}")
            print()
        sys.exit(0)

    from app.cli.config_loader import CLIConfig
    from app.cli.pipeline import Pipeline

    config = CLIConfig.from_args(args)
    pipeline = Pipeline(config, json_output=json_output, hitl=not no_hitl)

    try:
        result = pipeline.run(args)
        if json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(EXIT_CANCELLED)
    except OpenVCError as exc:
        # Typed errors carry their own exit code and type slug
        if json_output:
            print(json.dumps(exc.to_dict(), ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except Exception as exc:
        # Classify unknown exceptions by message heuristics
        typed = classify_exception(exc)
        if json_output:
            print(json.dumps(typed.to_dict(), ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(typed.exit_code)


def _describe_dry_run(args) -> dict:
    """Return a human/JSON description of what `process` would do."""
    command = getattr(args, "command", "")
    steps = []

    if command == "process":
        inp = str(getattr(args, "input", ""))
        steps.append(f"Input: {inp}")
        is_url = inp.startswith("http://") or inp.startswith("https://")
        if is_url:
            steps.append("yt-dlp: attempt transcript download (skip full video if available)")
            steps.append("yt-dlp: download 720p video if transcript unavailable or video needed")
        else:
            steps.append("ffmpeg: extract audio from local file")
            steps.append("bijian ASR: transcribe audio")
        steps.append("subtitle processing: rule-based split → optimize → translate")
        if getattr(args, "translate", None):
            steps.append(f"LLM translation → {args.translate}")
        if not getattr(args, "no_video", False):
            steps.append(f"ffmpeg: synthesize captioned video ({getattr(args, 'quality', 'medium')} quality)")
        if getattr(args, "slice", False):
            steps.append(f"LLM slice: extract ~{getattr(args, 'slice_count', 5)} semantic clips")
        output = str(getattr(args, "output", "./output"))
        steps.append(f"Output directory: {output}")

    elif command == "slice":
        steps.append(f"Load subtitle: {getattr(args, 'subtitle', '')}")
        steps.append(f"LLM analysis: identify ~{getattr(args, 'count', 5)} clips about '{getattr(args, 'topic', 'most informative segments')}'")
        steps.append(f"ffmpeg: trim {getattr(args, 'count', 5)} clips → {getattr(args, 'output_dir', './slices')}")
    else:
        steps.append(f"command: {command}")

    return {"command": command, "dry_run": True, "steps": steps}


if __name__ == "__main__":
    main()
