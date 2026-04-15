import os
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import ClockConfig, NotificationsConfig


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except (IOError, OSError):
        return ImageFont.load_default()


def _fit_font_size(
    font_path: str, text: str, max_width: int, max_height: int, padding: float = 0.9
) -> ImageFont.FreeTypeFont:
    """Binary-search for the largest font size where text fits within the given area."""
    target_w = int(max_width * padding)
    target_h = int(max_height * padding)
    lo, hi = 8, max(max_width, max_height)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(font_path, mid)
        bbox = font.getbbox(text)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= target_w and h <= target_h:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return _load_font(font_path, best)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = []
        for word in words:
            test = " ".join(current + [word])
            bbox = font.getbbox(test)
            if bbox[2] - bbox[0] <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
    return lines


def _make_background(
    image_path: str, fallback_color, width: int, height: int
) -> Image.Image:
    """Return an RGB image sized (width, height). Uses image_path if valid, else solid color."""
    if image_path and os.path.exists(image_path):
        try:
            bg = Image.open(image_path).convert("RGB")
            bg = bg.resize((width, height), Image.LANCZOS)
            return bg
        except Exception:
            pass
    return Image.new("RGB", (width, height), fallback_color)


def _load_icon(icon_path: str, size: int) -> Optional[Image.Image]:
    if not icon_path or not os.path.exists(icon_path):
        return None
    try:
        if icon_path.lower().endswith(".icns"):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            result = subprocess.run(
                ["sips", "-s", "format", "png", icon_path, "--out", tmp_path],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            icon = Image.open(tmp_path).convert("RGBA")
            os.unlink(tmp_path)
        else:
            icon = Image.open(icon_path).convert("RGBA")
        icon = icon.resize((size, size), Image.LANCZOS)
        return icon
    except Exception:
        return None


def render_clock(cfg: ClockConfig, width: int, height: int) -> Image.Image:
    img = _make_background(cfg.background_image, cfg.background_color, width, height)
    draw = ImageDraw.Draw(img)

    time_str = datetime.now().strftime(cfg.format)

    if cfg.font_size == 0:
        # Use a representative string (widest likely time) to avoid size jumping each minute
        sample = time_str.replace("0", "8").replace("1", "8")
        font = _fit_font_size(cfg.font, sample, width, height)
    else:
        font = _load_font(cfg.font, cfg.font_size)
    bbox = font.getbbox(time_str)
    # bbox = (left, top, right, bottom) — left/top may be non-zero due to font bearing
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) // 2 - bbox[0]

    if cfg.position == "top":
        y = 20 - bbox[1]
    elif cfg.position == "bottom":
        y = height - text_h - 20 - bbox[1]
    else:  # center
        y = (height - text_h) // 2 - bbox[1]

    draw.text((x, y), time_str, font=font, fill=cfg.color)
    return img


def render_notification(
    app_name: str,
    title: str,
    message: str,
    icon_path: str,
    cfg: NotificationsConfig,
    width: int,
    height: int,
) -> Image.Image:
    img = _make_background(cfg.background_image, cfg.background_color, width, height)
    draw = ImageDraw.Draw(img)

    padding = 10
    icon_size = cfg.icon_size

    # --- Header: icon + app name ---
    icon = _load_icon(icon_path, icon_size)
    header_h = icon_size + padding * 2

    if icon:
        # Paste icon with alpha mask if available
        icon_x = padding
        icon_y = padding
        if icon.mode == "RGBA":
            img.paste(icon, (icon_x, icon_y), icon)
        else:
            img.paste(icon, (icon_x, icon_y))
        app_name_x = icon_x + icon_size + padding
    else:
        app_name_x = padding

    # App name beside icon
    font_app = _load_font(cfg.font, cfg.title_font_size)
    app_name_y = padding + (icon_size - cfg.title_font_size) // 2
    draw.text((app_name_x, app_name_y), app_name, font=font_app, fill=cfg.text_color)

    # Divider line
    divider_y = header_h + padding // 2
    draw.line(
        [(padding, divider_y), (width - padding, divider_y)],
        fill=(80, 80, 100),
        width=1,
    )

    # --- Body: title + message ---
    body_y = divider_y + padding
    max_text_w = width - padding * 2

    font_title = _load_font(cfg.font, cfg.title_font_size)
    font_body = _load_font(cfg.font, cfg.body_font_size)

    if title:
        title_lines = _wrap_text(title, font_title, max_text_w)
        for line in title_lines:
            draw.text((padding, body_y), line, font=font_title, fill=cfg.text_color)
            bbox = font_title.getbbox(line)
            body_y += (bbox[3] - bbox[1]) + 4
        body_y += 6  # extra gap between title and body

    if message:
        body_lines = _wrap_text(message, font_body, max_text_w)
        body_color = tuple(min(255, c + 40) for c in cfg.background_color)
        # Use a slightly lighter color for body text
        body_text_color = tuple(
            max(0, c - 30) if c > 128 else min(255, c + 60)
            for c in cfg.text_color
        )
        for line in body_lines:
            if body_y + cfg.body_font_size > height - padding:
                break
            draw.text((padding, body_y), line, font=font_body, fill=body_text_color)
            bbox = font_body.getbbox(line) if line else (0, 0, 0, cfg.body_font_size)
            body_y += (bbox[3] - bbox[1]) + 4

    return img
