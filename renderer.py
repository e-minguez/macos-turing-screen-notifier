import math
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import ClockConfig, NotificationsConfig, WeatherConfig


_font_cache: dict = {}


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except (IOError, OSError):
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


_fit_cache: dict = {}


def _fit_font_size(
    font_path: str, text: str, max_width: int, max_height: int, padding: float = 0.9
) -> ImageFont.FreeTypeFont:
    """Binary-search for the largest font size where text fits within the given area."""
    key = (font_path, text, max_width, max_height, padding)
    if key in _fit_cache:
        return _fit_cache[key]
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
    result = _load_font(font_path, best)
    _fit_cache[key] = result
    return result


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


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    weather_code: int,
    is_day: int,
) -> None:
    """Draw a geometric weather icon centered at (cx, cy) within a size×size box."""
    s = size
    r = max(2, s // 3)

    def _cloud(ox, oy, w, h, color=(180, 180, 180)):
        draw.ellipse([ox - w // 2, oy - h // 4, ox + w // 2, oy + h // 2], fill=color)
        draw.ellipse([ox - w // 3, oy - h // 2, ox + w // 6, oy + h // 4], fill=color)
        draw.ellipse([ox, oy - h // 3, ox + w // 2 - 2, oy + h // 4], fill=color)

    def _sun(ox, oy, r, color=(255, 200, 0)):
        draw.ellipse([ox - r, oy - r, ox + r, oy + r], fill=color)
        ray = max(2, s // 6)
        for deg in range(0, 360, 45):
            a = math.radians(deg)
            draw.line(
                [ox + int((r + 1) * math.cos(a)), oy + int((r + 1) * math.sin(a)),
                 ox + int((r + ray) * math.cos(a)), oy + int((r + ray) * math.sin(a))],
                fill=color, width=max(1, s // 14),
            )

    if weather_code == 0:
        if is_day:
            _sun(cx, cy, r)
        else:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(200, 210, 255))
    elif weather_code in (1, 2):
        _sun(cx + s // 5, cy - s // 6, max(2, r * 2 // 3))
        _cloud(cx - s // 8, cy + s // 8, int(s * 0.55), int(s * 0.35))
    elif weather_code == 3:
        _cloud(cx, cy, int(s * 0.7), int(s * 0.4))
    elif weather_code in (45, 48):
        lw = max(1, s // 10)
        for i in range(3):
            y = cy - r + i * r
            draw.line([cx - r, y, cx + r, y], fill=(160, 160, 160), width=lw)
    elif weather_code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        _cloud(cx, cy - s // 6, int(s * 0.65), int(s * 0.35))
        lw = max(1, s // 12)
        for dx in (-s // 5, 0, s // 5):
            draw.line([cx + dx, cy + s // 6, cx + dx - 2, cy + s // 2 - 2],
                      fill=(80, 140, 255), width=lw)
    elif weather_code in (71, 73, 75, 77, 85, 86):
        _cloud(cx, cy - s // 6, int(s * 0.65), int(s * 0.35))
        rd = max(1, s // 10)
        for dx in (-s // 5, 0, s // 5):
            x = cx + dx
            draw.ellipse([x - rd, cy + s // 4 - rd, x + rd, cy + s // 4 + rd],
                         fill=(220, 235, 255))
    elif weather_code in (95, 96, 99):
        _cloud(cx, cy - s // 6, int(s * 0.65), int(s * 0.35), color=(110, 110, 130))
        pts = [
            (cx + s // 8,  cy + s // 6),
            (cx - s // 8,  cy + s // 3),
            (cx + s // 12, cy + s // 3),
            (cx - s // 6,  cy + s // 2),
        ]
        draw.line(pts, fill=(255, 210, 0), width=max(1, s // 8))
    else:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(150, 150, 150))


def render_clock(cfg: ClockConfig, width: int, height: int,
                 weather_data: Optional[dict] = None,
                 weather_cfg: Optional[WeatherConfig] = None) -> Image.Image:
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

    draw.text(
        (x, y),
        time_str,
        font=font,
        fill=cfg.color,
        stroke_width=cfg.stroke_width,
        stroke_fill=cfg.stroke_color if cfg.stroke_width else None,
    )

    if weather_cfg and weather_data:
        # Build list of enabled display elements
        elements = []
        if weather_cfg.show_icon:
            elements.append(("icon",))
        if weather_cfg.show_temperature:
            elements.append(("text", f"{weather_data['temperature']:.0f}{weather_data['unit']}"))
        if weather_cfg.show_condition:
            elements.append(("text", weather_data["condition"]))

        if elements:
            wfont = _load_font(cfg.font, weather_cfg.font_size)
            icon_sz = weather_cfg.font_size + 4
            gap = 4

            # Measure each element
            el_widths = []
            el_heights = []
            el_bboxes = []
            for el in elements:
                if el[0] == "icon":
                    el_widths.append(icon_sz)
                    el_heights.append(icon_sz)
                    el_bboxes.append(None)
                else:
                    bb = wfont.getbbox(el[1])
                    el_widths.append(bb[2] - bb[0])
                    el_heights.append(bb[3] - bb[1])
                    el_bboxes.append(bb)

            total_w = sum(el_widths) + gap * (len(elements) - 1)
            row_h = max(el_heights)

            # Determine starting position
            wpad = 8
            pos = weather_cfg.position
            if pos in ("bottom", "top"):
                x_start = (width - total_w) // 2
            elif pos in ("top-left", "bottom-left"):
                x_start = wpad
            else:  # top-right, bottom-right
                x_start = width - total_w - wpad

            if pos in ("top", "top-left", "top-right"):
                y_start = wpad
            else:  # bottom, bottom-left, bottom-right
                y_start = height - row_h - wpad

            # Draw semi-transparent background box if requested
            if weather_cfg.background_opacity > 0:
                alpha = int(max(0, min(100, weather_cfg.background_opacity)) / 100 * 255)
                r, g, b = weather_cfg.background_color
                box_pad = 6
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                ImageDraw.Draw(overlay).rectangle(
                    [x_start - box_pad, y_start - box_pad,
                     x_start + total_w + box_pad, y_start + row_h + box_pad],
                    fill=(r, g, b, alpha),
                )
                img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
                draw = ImageDraw.Draw(img)

            # Draw each element left to right
            wx = x_start
            for i, (el, ew, eh, eb) in enumerate(zip(elements, el_widths, el_heights, el_bboxes)):
                if el[0] == "icon":
                    _draw_weather_icon(
                        draw,
                        wx + icon_sz // 2,
                        y_start + row_h // 2,
                        icon_sz,
                        weather_data["weather_code"],
                        weather_data.get("is_day", 1),
                    )
                else:
                    text_y = y_start + (row_h - eh) // 2 - (eb[1] if eb else 0)
                    draw.text((wx, text_y), el[1], font=wfont, fill=weather_cfg.color)
                wx += ew + (gap if i < len(elements) - 1 else 0)

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

    if cfg.overlay_clock:
        now_str = datetime.now().strftime(cfg.overlay_clock_format)
        font_overlay = _load_font(cfg.font, cfg.overlay_clock_font_size)
        bbox = draw.textbbox((0, 0), now_str, font=font_overlay)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        ovl_padding = 6
        pos_map = {
            "bottom-right": (width - tw - ovl_padding, height - th - ovl_padding),
            "bottom-left":  (ovl_padding,               height - th - ovl_padding),
            "top-right":    (width - tw - ovl_padding,  ovl_padding),
            "top-left":     (ovl_padding,               ovl_padding),
        }
        ox, oy = pos_map.get(cfg.overlay_clock_position, pos_map["bottom-right"])
        draw.text((ox, oy), now_str, font=font_overlay, fill=cfg.overlay_clock_color)

    return img
