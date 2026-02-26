import platform
from typing import Optional

from app.config import SUBTITLE_STYLE_PATH


def get_subtitle_style(style_name: str) -> Optional[str]:
    """获取字幕样式内容

    Args:
        style_name: 样式名称

    Returns:
        str: 样式内容字符串，如果样式文件不存在则返回None
    """
    style_path = SUBTITLE_STYLE_PATH / f"{style_name}.txt"
    if style_path.exists():
        return style_path.read_text(encoding="utf-8")
    return None


def generate_adaptive_style(
    video_width: int,
    video_height: int,
    layout: str = "bilingual",
    style_preset: str = "default",
    primary_font: Optional[str] = None,
    secondary_font: Optional[str] = None,
) -> str:
    is_portrait = video_height > video_width
    is_hd = video_width >= 1280

    system = platform.system()
    if system == "Darwin":
        default_cjk_font = "PingFang SC"
    elif system == "Windows":
        default_cjk_font = "Microsoft YaHei"
    else:
        default_cjk_font = "Noto Sans CJK SC"

    font = primary_font or default_cjk_font

    if is_portrait:
        primary_size = 48 if is_hd else 36
    else:
        primary_size = 40 if is_hd else 28

    secondary_size = max(primary_size - 10, 18)

    secondary_margin_v = int(video_height * 0.05)
    margin_h = int(video_width * 0.02)

    overrides = _get_preset_overrides(style_preset)
    outline_px = int(overrides.get('outline', '2'))
    # Primary (Default) MarginV is anchored independently above Secondary:
    # secondary_margin_v + secondary line height estimate + gap
    primary_margin_v = secondary_margin_v + secondary_size + outline_px * 2 + 16

    style = (
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{primary_size},"
        f"{overrides.get('primary_color', '&H00FFFFFF')},"
        f"&H000000FF,&H00000000,"
        f"{overrides.get('back_color', '&H80000000')},"
        f"-1,0,0,0,100,100,0,0,"
        f"{overrides.get('border_style', '1')},"
        f"{overrides.get('outline', '2')},1,2,"
        f"{margin_h},{margin_h},{primary_margin_v},1\n"
        f"Style: Secondary,{secondary_font or font},{secondary_size},"
        f"&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"-1,0,0,0,100,100,0,0,"
        f"{overrides.get('border_style', '1')},"
        f"{overrides.get('outline', '2')},0,2,"
        f"{margin_h},{margin_h},{secondary_margin_v},1\n"
    )
    return style


def _get_preset_overrides(preset: str) -> dict:
    presets = {
        "default":       {"primary_color": "&H00FFFFFF", "border_style": "1", "outline": "2"},
        "highlight-bg":  {"primary_color": "&H00FFFFFF", "border_style": "4", "outline": "10",
                          "back_color": "&HAA000000"},
        "minimal":       {"primary_color": "&H00FFFFFF", "border_style": "1", "outline": "0"},
        "terminal-dark": {"primary_color": "&H0041FF00", "border_style": "4", "outline": "8",
                          "back_color": "&HCC000000"},
        "documentary":   {"primary_color": "&H00FFFFCC", "border_style": "1", "outline": "3"},
        "social-media":  {"primary_color": "&H0000FFFF", "border_style": "1", "outline": "3"},
    }
    return presets.get(preset, {})


def recommended_line_length(video_width: int, is_cjk: bool) -> int:
    if is_cjk:
        return int(video_width * 0.80 / 38.0)
    return int(video_width * 0.80 / 60.0)
