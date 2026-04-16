# CLAUDE.md — Turing Smart Screen Notification Hub

## Project Overview
A macOS Python app that drives a Turing Smart Screen to show:
1. A configurable clock (updates every minute)
2. macOS notification alerts (app icon + app name + title + body), displayed temporarily before returning to the clock

## Key Architectural Decisions

### Notification Source: Database Polling (not PyObjC)
There is **no public macOS API** to receive notifications from other apps. We use kqueue-based monitoring of the macOS notification SQLite database in `notification_listener.py`. This is the most reliable approach available.

- Database path: `~/Library/Group Containers/group.com.apple.usernoted/db2/db`
- Requires **Full Disk Access** granted to the terminal app (System Settings → Privacy & Security → Full Disk Access)
- `notification_listener.py` runs as a **subprocess** and emits JSON lines to stdout
- **Do NOT** use NSDistributedNotificationCenter — it only captures inter-process IPC, not user-visible notification center alerts

### Display Library
- Uses `turing-smart-screen-python/` (local directory, not pip-installed)
- All display code adds `sys.path.insert(0, "turing-smart-screen-python")` before imports
- Hardware: `LcdCommRevA` for real Turing 3.5" screen, `LcdSimulated` for development
- Config `display.revision: "SIMU"` for testing without hardware

### State Machine
Two states: `CLOCK` and `NOTIFICATION`
- Clock re-renders only when the formatted time string changes — every minute with `%H:%M`, every second with `%H:%M:%S`
- Notification display interrupts clock for `notifications.display_duration` seconds
- Notification subprocess runs in a background thread, feeds a `queue.Queue`

### Background Images
Both `ClockConfig` and `NotificationsConfig` have an optional `background_image` field (path to any PIL-supported image file). When set, `_make_background()` in `renderer.py` loads and scales the image to fit the screen, replacing the solid `background_color`. Falls back to `background_color` if the path is missing or the file fails to load. Ready-made images sized for Turing screens live in `turing-smart-screen-python/res/backgrounds/`.

### Clock Text Outline
`ClockConfig` has `stroke_width` (int, default `0`) and `stroke_color` (RGB tuple) fields. When `stroke_width > 0`, Pillow's built-in `stroke_width`/`stroke_fill` parameters on `draw.text()` are used — no manual offset drawing needed. Useful for readability over background images.

### Clock Overlay on Notifications
`NotificationsConfig` has five overlay fields: `overlay_clock` (bool, default `True`), `overlay_clock_position` (str, default `"bottom-right"`), `overlay_clock_font_size` (int, default `20`), `overlay_clock_color` (RGB tuple, default white), and `overlay_clock_format` (str, default `"%H:%M"`). When `overlay_clock` is `True`, the end of `render_notification()` in `renderer.py` draws the current time in the specified corner using `draw.textbbox()` to measure text size and a dict mapping position name → `(x, y)` with 6 px padding. Valid positions: `"bottom-right"`, `"bottom-left"`, `"top-right"`, `"top-left"`.

### Weather Display
`WeatherConfig` (11 fields) lives in `config.py`. Key fields: `enabled`, `latitude`, `longitude`, `temperature_unit` (`"celsius"`/`"fahrenheit"`), `refresh_interval` (minutes), `show_icon`, `show_temperature`, `show_condition`, `font_size`, `color`, `position`.

**`weather.py`** — `WeatherService` runs a single daemon thread (`threading.Thread(daemon=True)`). On start it fetches immediately, then sleeps `refresh_interval * 60` seconds between fetches. Calls Open-Meteo: `https://api.open-meteo.com/v1/forecast?current=temperature_2m,weather_code,is_day`. Returns `{"temperature", "weather_code", "is_day", "condition", "unit"}`. On error, keeps last good data (no crash); logs to stderr. Thread-safe `get()` uses a `threading.Lock`.

**`renderer.py`** — `_draw_weather_icon(draw, cx, cy, size, weather_code, is_day)` draws PIL geometric icons using `draw.ellipse()`, `draw.line()`, `draw.polygon()`. WMO code groups: 0=sun/moon, 1-2=partly cloudy, 3=overcast, 45/48=fog lines, 51-67/80-82=rain (cloud+drops), 71-77/85-86=snow (cloud+dots), 95-99=thunder (cloud+bolt). `render_clock()` signature extended with `weather_data: Optional[dict] = None` and `weather_cfg: Optional[WeatherConfig] = None`. Weather row is assembled from enabled elements (icon, temp text, condition text) measured individually, laid out left-to-right with 4px gaps, positioned using `weather_cfg.position` (6 positions: top/bottom + 4 corners, 8px padding).

**`main.py`** — `WeatherService` is started after `init_display()` if `cfg.weather.enabled`. `last_weather` is tracked alongside `last_minute`; clock re-renders when either changes (so weather update mid-minute still refreshes the display).

**Do NOT** add weather icons as image files — the PIL-drawn approach requires no external assets and works at any size.

### Icon Handling
App icons come as `.icns` files from `notification_listener.py` (resolved via `mdfind` + `Info.plist`).
Convert to PNG using the built-in macOS `sips` tool:
```bash
sips -s format png /path/to/icon.icns --out /tmp/icon_converted.png
```
PIL then loads the PNG. Falls back to a blank colored square if conversion fails.

## File Structure
```
macos-notification-turing-screen/
├── CLAUDE.md                    # This file
├── README.md                    # User-facing docs
├── config.yaml                  # User configuration (edit this)
├── config.py                    # Loads config.yaml, provides defaults
├── renderer.py                  # PIL rendering: render_clock(), render_notification()
├── weather.py                   # WeatherService: Open-Meteo fetch + background thread
├── notification_listener.py     # kqueue notification watcher (run as subprocess)
├── main.py                      # Entry point: display init + event loop
├── requirements.txt
└── turing-smart-screen-python/  # Turing library (local, not pip)
```

## Running
```bash
cd macos-notification-turing-screen/
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Testing Without Hardware
Set `display.revision: "SIMU"` in `config.yaml`. The simulated display opens a window.

## Common Pitfalls
- Serial port detection: set `display.com_port: "AUTO"` or specify manually (e.g., `/dev/cu.usbserial-XXXX`)
- Font paths in `config.yaml` are relative to `macos-notification-turing-screen/`
- The notification listener needs ~5-10s latency (macOS buffers to disk before kqueue fires)
- On macOS Sequoia+, the terminal needs Full Disk Access for the notification DB
