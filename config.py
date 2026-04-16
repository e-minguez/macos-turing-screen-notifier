import os
from dataclasses import dataclass, field
from typing import Tuple

import yaml
from PIL import ImageColor


def _parse_color(value) -> Tuple[int, int, int]:
    if isinstance(value, (list, tuple)):
        return tuple(int(c) for c in value)
    return ImageColor.getrgb(str(value))[:3]


@dataclass
class DisplayConfig:
    revision: str = "SIMU"
    com_port: str = "AUTO"
    width: int = 320
    height: int = 480
    orientation: str = "PORTRAIT"
    brightness: int = 50


@dataclass
class ClockConfig:
    font: str = "turing-smart-screen-python/res/fonts/roboto/Roboto-Bold.ttf"
    font_size: int = 80
    color: Tuple[int, int, int] = field(default_factory=lambda: (255, 255, 255))
    background_color: Tuple[int, int, int] = field(default_factory=lambda: (0, 0, 0))
    background_image: str = ""
    format: str = "%H:%M"
    position: str = "center"
    stroke_width: int = 0
    stroke_color: Tuple[int, int, int] = field(default_factory=lambda: (0, 0, 0))


@dataclass
class NotificationsConfig:
    display_duration: int = 8
    icon_size: int = 64
    font: str = "turing-smart-screen-python/res/fonts/roboto/Roboto-Bold.ttf"
    title_font_size: int = 20
    body_font_size: int = 16
    text_color: Tuple[int, int, int] = field(default_factory=lambda: (255, 255, 255))
    background_color: Tuple[int, int, int] = field(
        default_factory=lambda: (26, 26, 46)
    )
    background_image: str = ""
    overlay_clock: bool = True
    overlay_clock_position: str = "bottom-right"
    overlay_clock_font_size: int = 20
    overlay_clock_color: Tuple[int, int, int] = field(default_factory=lambda: (255, 255, 255))
    overlay_clock_format: str = "%H:%M"


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    clock: ClockConfig = field(default_factory=ClockConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        return Config()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    display_raw = raw.get("display", {})
    clock_raw = raw.get("clock", {})
    notif_raw = raw.get("notifications", {})

    display = DisplayConfig(
        revision=display_raw.get("revision", "SIMU"),
        com_port=display_raw.get("com_port", "AUTO"),
        width=int(display_raw.get("width", 320)),
        height=int(display_raw.get("height", 480)),
        orientation=display_raw.get("orientation", "PORTRAIT"),
        brightness=int(display_raw.get("brightness", 50)),
    )

    clock = ClockConfig(
        font=clock_raw.get(
            "font",
            "turing-smart-screen-python/res/fonts/roboto/Roboto-Bold.ttf",
        ),
        font_size=int(clock_raw.get("font_size", 80)),
        color=_parse_color(clock_raw.get("color", "#FFFFFF")),
        background_color=_parse_color(clock_raw.get("background_color", "#000000")),
        background_image=clock_raw.get("background_image", ""),
        format=clock_raw.get("format", "%H:%M"),
        position=clock_raw.get("position", "center"),
        stroke_width=int(clock_raw.get("stroke_width", 0)),
        stroke_color=_parse_color(clock_raw.get("stroke_color", "#000000")),
    )

    notifications = NotificationsConfig(
        display_duration=int(notif_raw.get("display_duration", 8)),
        icon_size=int(notif_raw.get("icon_size", 64)),
        font=notif_raw.get(
            "font",
            "turing-smart-screen-python/res/fonts/roboto/Roboto-Bold.ttf",
        ),
        title_font_size=int(notif_raw.get("title_font_size", 20)),
        body_font_size=int(notif_raw.get("body_font_size", 16)),
        text_color=_parse_color(notif_raw.get("text_color", "#FFFFFF")),
        background_color=_parse_color(
            notif_raw.get("background_color", "#1a1a2e")
        ),
        background_image=notif_raw.get("background_image", ""),
        overlay_clock=bool(notif_raw.get("overlay_clock", True)),
        overlay_clock_position=notif_raw.get("overlay_clock_position", "bottom-right"),
        overlay_clock_font_size=int(notif_raw.get("overlay_clock_font_size", 20)),
        overlay_clock_color=_parse_color(notif_raw.get("overlay_clock_color", "#FFFFFF")),
        overlay_clock_format=notif_raw.get("overlay_clock_format", "%H:%M"),
    )

    return Config(display=display, clock=clock, notifications=notifications)
