import json
import os
import queue
import signal
import subprocess
import sys
import time
from datetime import datetime
from threading import Event, Thread

sys.path.insert(0, "turing-smart-screen-python")

from library.lcd.lcd_comm_rev_a import LcdCommRevA, Orientation
from library.lcd.lcd_simulated import LcdSimulated

from config import load_config
from renderer import render_clock, render_notification

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LISTENER_PATH = os.path.join(SCRIPT_DIR, "notification_listener.py")


def init_display(cfg):
    revision = cfg.display.revision.upper()
    w, h = cfg.display.width, cfg.display.height

    if revision == "SIMU":
        lcd = LcdSimulated(display_width=w, display_height=h)
    elif revision == "A":
        lcd = LcdCommRevA(com_port=cfg.display.com_port, display_width=w, display_height=h)
    else:
        print(f"Unknown display revision: {revision}", file=sys.stderr)
        sys.exit(1)

    lcd.Reset()
    lcd.InitializeComm()
    lcd.SetBrightness(level=cfg.display.brightness)

    orientation_map = {
        "0": Orientation.PORTRAIT,
        "PORTRAIT": Orientation.PORTRAIT,
        "90": Orientation.LANDSCAPE,
        "LANDSCAPE": Orientation.LANDSCAPE,
        "180": Orientation.REVERSE_PORTRAIT,
        "REVERSE_PORTRAIT": Orientation.REVERSE_PORTRAIT,
        "270": Orientation.REVERSE_LANDSCAPE,
        "REVERSE_LANDSCAPE": Orientation.REVERSE_LANDSCAPE,
    }
    lcd.SetOrientation(orientation_map.get(str(cfg.display.orientation).upper(), Orientation.PORTRAIT))
    return lcd


def notification_reader(proc: subprocess.Popen, notif_queue: queue.Queue, stop: Event):
    for raw_line in proc.stdout:
        if stop.is_set():
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            notif_queue.put(data)
        except json.JSONDecodeError:
            pass
    proc.wait()


def main():
    os.chdir(SCRIPT_DIR)
    config_path = "config.local.yaml" if os.path.exists("config.local.yaml") else "config.yaml"
    cfg = load_config(config_path)

    stop = Event()

    def shutdown(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    lcd = init_display(cfg)
    w, h = lcd.get_width(), lcd.get_height()

    # Start notification listener subprocess
    proc = subprocess.Popen(
        [sys.executable, LISTENER_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    notif_queue: queue.Queue = queue.Queue()
    reader_thread = Thread(
        target=notification_reader,
        args=(proc, notif_queue, stop),
        daemon=True,
    )
    reader_thread.start()

    print("Running. Press Ctrl+C to stop.")

    STATE_CLOCK = "clock"
    STATE_NOTIFICATION = "notification"
    state = STATE_CLOCK

    last_minute = ""
    notif_shown_at = 0.0

    # Render initial clock immediately
    img = render_clock(cfg.clock, w, h)
    lcd.DisplayPILImage(img)
    last_minute = datetime.now().strftime(cfg.clock.format)

    while not stop.is_set():
        now = time.monotonic()

        # Check for new notifications (non-blocking)
        try:
            notif = notif_queue.get_nowait()
        except queue.Empty:
            notif = None

        if notif:
            state = STATE_NOTIFICATION
            notif_shown_at = now
            img = render_notification(
                app_name=notif.get("app_name", ""),
                title=notif.get("title", ""),
                message=notif.get("message", ""),
                icon_path=notif.get("icon_path", ""),
                cfg=cfg.notifications,
                width=w,
                height=h,
            )
            lcd.DisplayPILImage(img)

        elif state == STATE_NOTIFICATION:
            if now - notif_shown_at >= cfg.notifications.display_duration:
                state = STATE_CLOCK
                last_minute = ""  # Force clock redraw

        if state == STATE_CLOCK:
            current_minute = datetime.now().strftime(cfg.clock.format)
            if current_minute != last_minute:
                img = render_clock(cfg.clock, w, h)
                lcd.DisplayPILImage(img)
                last_minute = current_minute

        time.sleep(1)

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    lcd.closeSerial()
    print("Stopped.")


if __name__ == "__main__":
    main()
