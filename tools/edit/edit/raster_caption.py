"""Render captions as small RGBA layers on FFmpeg builds without drawtext."""

import os
from pathlib import Path


def caption_font(text, size, preferred=None):
    try:
        from PIL import ImageFont
    except ImportError as exc:
        raise ValueError("Install Pillow for raster captions on this FFmpeg build") from exc

    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        *([preferred] if preferred else []),
        windows / "arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        windows / "msyhbd.ttc",
        windows / "simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    needed = {ch for ch in text if not ch.isspace()}
    # FreeType renders unassigned code points using glyph zero (.notdef).
    # Check ink and shape rather than trusting the font family or filename.
    missing = needed
    for candidate in [*candidates, None]:
        if candidate is not None and not Path(candidate).is_file():
            continue
        try:
            font = (
                ImageFont.truetype(str(candidate), size)
                if candidate
                else ImageFont.load_default(size=size)
            )
            absent = font.getmask(chr(0x10FFFF), mode="L")
            signature = absent.size, bytes(absent)
            missing = set()
            for char in needed:
                glyph = font.getmask(char, mode="L")
                if glyph.getbbox() is None or (glyph.size, bytes(glyph)) == signature:
                    missing.add(char)
            if not missing:
                return font
        except (OSError, UnicodeError, TypeError):
            continue
    codes = " ".join(f"U+{ord(ch):04X}" for ch in sorted(missing or needed)[:8])
    raise ValueError(
        f"No installed caption font covers the text ({codes}). "
        "Set the plan's font to a font file covering those characters."
    )


def caption_image(path, text, width, preferred):
    size = max(10, round(width * 64 / 1080))
    stroke = max(1, round(width * 7 / 1080))
    font = caption_font(text, size, preferred)
    from PIL import Image, ImageDraw

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = dummy.multiline_textbbox((0, 0), text, font, stroke_width=stroke)
    image = Image.new("RGBA", (max(1, right - left), max(1, bottom - top)))
    ImageDraw.Draw(image).multiline_text(
        (-left, -top),
        text,
        fill="white",
        font=font,
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 217),
        align="center",
    )
    image.save(path)
