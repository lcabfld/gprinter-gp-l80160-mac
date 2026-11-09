#!/usr/bin/env python3
"""Local web app for the GP-L80160: upload photos, preview them, print a queue.

    server.py                  serve on http://localhost:8765
    server.py --dry-run        pretend to print, without touching the printer
"""
import argparse
import io
import json
import re
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, UnidentifiedImageError

import thermal
from document import add_caption, render_markdown, render_svg

PORT = 8765
TEXT_FILES = (".md", ".markdown", ".txt")
TEXT_ROW_DELAY = 0.01  # text doesn't need the slow, careful printing photos do
MAX_UPLOAD = 100 * 1024 * 1024
JOB_GAP = 5  # seconds between prints, to tear one off before the next starts
SETTINGS_FILE = Path.home() / "Library/Application Support/Thermal Printer/settings.json"
DEFAULTS = {
    "exposure": 0.0,
    "contrast": thermal.PHOTO_CONTRAST,
    "gamma": thermal.PHOTO_GAMMA,
    "cutoff": thermal.PHOTO_CUTOFF,
    "delay": thermal.USB_CHUNK_DELAY * 1000,
    "caption": False,
    "autoprint": True,
}
LIMITS = {"exposure": (-1.5, 1.5), "contrast": (0.5, 1.5), "gamma": (0.5, 1.3), "cutoff": (0, 5), "delay": (10, 60)}


def clean_settings(values):
    settings = {
        "caption": values.get("caption") in (True, "true"),
        "autoprint": values.get("autoprint", True) in (True, "true"),
    }
    for key, (low, high) in LIMITS.items():
        try:
            settings[key] = min(high, max(low, float(values.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError):
            settings[key] = DEFAULTS[key]
    return settings


def load_settings():
    try:
        return clean_settings(json.loads(SETTINGS_FILE.read_text()))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings))


def preview_png(image):
    preview = io.BytesIO()
    image.convert("1").save(preview, "PNG")
    return preview.getvalue()


def adjusted(base, settings):
    photo = thermal.adjust_photo(
        base, settings["cutoff"], settings["gamma"], settings["contrast"], settings["exposure"]
    )
    if not settings["caption"]:
        return photo
    # Hard black and white first, so dithering can't speckle the caption text.
    text = (
        f"EV{settings['exposure']:+.1f} C{settings['contrast']:.2f} G{settings['gamma']:.2f} "
        f"L{settings['cutoff']:.1f} D{settings['delay']:.0f}"
    )
    return add_caption(photo.convert("1").convert("L"), text)
PAGE = Path(__file__).with_name("index.html")
FONTS = Path(__file__).with_name("fonts")
FONT_FILES = {"/fonts/geist.ttf": "Geist[wght].ttf", "/fonts/geist-mono.ttf": "GeistMono[wght].ttf"}


class Job:
    next_id = 1

    def __init__(self, name, image, preview, row_delay=None, base=None, held=False):
        self.id = Job.next_id
        Job.next_id += 1
        self.name = name
        self.image = image
        self.preview = preview
        self.row_delay = row_delay
        self.base = base
        self.state = "held" if held else "queued"
        self.error = None
        self.stop = False

    def summary(self):
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "error": self.error,
            "height": self.image.height,
        }


class Queue:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.settings = load_settings()
        self.last_photo = None
        self.last_name = None
        self.jobs = []
        self.changed = threading.Condition()
        threading.Thread(target=self._work, daemon=True).start()

    def add(self, job):
        with self.changed:
            self.jobs.append(job)
            self.changed.notify()

    def get(self, job_id):
        with self.changed:
            return next((j for j in self.jobs if j.id == job_id), None)

    def summaries(self):
        with self.changed:
            return [j.summary() for j in self.jobs]

    def cancel(self, job):
        with self.changed:
            job.stop = True
            if job.state in ("queued", "held"):
                job.state = "cancelled"

    def release(self, job):
        """Start a held job, using the settings as they are now."""
        with self.changed:
            if job.state != "held":
                return
            if job.base is not None:
                job.image = adjusted(job.base, self.settings)
                job.preview = preview_png(job.image)
            job.state = "queued"
            self.changed.notify()

    def clear_finished(self):
        with self.changed:
            self.jobs = [j for j in self.jobs if j.state in ("queued", "printing", "held")]

    def _next(self):
        with self.changed:
            while True:
                job = next((j for j in self.jobs if j.state == "queued"), None)
                if job:
                    job.state = "printing"
                    return job
                self.changed.wait()

    def _print(self, job):
        if self.dry_run:
            time.sleep(1.5)
            return
        row_delay = job.row_delay or self.settings["delay"] / 1000
        with thermal.Printer(row_delay=row_delay) as printer:
            printer.image(job.image, should_stop=lambda: job.stop)
            printer.feed()

    def _work(self):
        while True:
            job = self._next()
            try:
                self._print(job)
                job.state = "cancelled" if job.stop else "done"
            except Exception as error:
                job.state = "failed"
                job.error = str(error)
            time.sleep(JOB_GAP)


class Handler(BaseHTTPRequestHandler):
    queue = None
    port = PORT

    def log_message(self, *_):
        pass

    def _allowed(self):
        # Only this page may drive the printer, not any website the browser
        # happens to have open.
        hosts = {f"localhost:{self.port}", f"127.0.0.1:{self.port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in hosts:
            return False
        return origin is None or origin.removeprefix("http://") in hosts

    def _send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, json.dumps(value).encode())

    def do_GET(self):
        if not self._allowed():
            return self._json(403, {"error": "forbidden"})
        url = urlparse(self.path)
        path = url.path
        if path == "/settings":
            return self._json(200, {"settings": self.queue.settings, "defaults": DEFAULTS})
        if path == "/adjust/preview":
            return self._adjust_preview({k: v[0] for k, v in parse_qs(url.query).items()})
        if path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if path in FONT_FILES:
            return self._send(200, (FONTS / FONT_FILES[path]).read_bytes(), "font/ttf")
        if path == "/jobs":
            connected =self.queue.dry_run or thermal.usb_connected()
            return self._json(
                200,
                {"connected": connected, "photo": self.queue.last_name, "jobs": self.queue.summaries()},
            )
        match = re.fullmatch(r"/jobs/(\d+)/preview", path)
        job = self.queue.get(int(match[1])) if match else None
        if job:
            return self._send(200, job.preview, "image/png")
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return self._json(403, {"error": "forbidden"})
        url = urlparse(self.path)
        if url.path == "/jobs":
            return self._upload(parse_qs(url.query).get("name", ["photo"])[0])
        if url.path == "/settings":
            self.queue.settings = clean_settings(self._body())
            save_settings(self.queue.settings)
            return self._json(200, self.queue.settings)
        if url.path == "/adjust/print":
            if self.queue.last_photo is None:
                return self._json(400, {"error": "Upload a photo first"})
            return self._queue_image(self.queue.last_name, adjusted(self.queue.last_photo, self.queue.settings))
        if url.path == "/jobs/clear":
            self.queue.clear_finished()
            return self._json(200, {})
        match = re.fullmatch(r"/jobs/(\d+)/(cancel|print)", url.path)
        job = self.queue.get(int(match[1])) if match else None
        if job:
            if match[2] == "print":
                self.queue.release(job)
            else:
                self.queue.cancel(job)
            return self._json(200, {})
        self._json(404, {"error": "not found"})

    def _upload(self, name):
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= MAX_UPLOAD:
            return self._json(413, {"error": "file too large"})
        data = self.rfile.read(size)
        try:
            if name.lower().endswith(TEXT_FILES):
                image = render_markdown(data.decode("utf-8-sig"), thermal.USB_MAX_DOTS)
            elif name.lower().endswith(".svg"):
                image = render_svg(data, thermal.USB_MAX_DOTS)
            else:
                image = self._photo(data, name)
        except UnicodeDecodeError:
            return self._json(400, {"error": "text file isn't UTF-8"})
        except ValueError as error:
            return self._json(400, {"error": str(error)})
        except (UnidentifiedImageError, OSError, subprocess.SubprocessError):
            return self._json(400, {"error": "not an image this app can read"})
        lower = name.lower()
        is_text = lower.endswith(TEXT_FILES)
        base = None if is_text or lower.endswith(".svg") else self.queue.last_photo
        held = not self.queue.settings["autoprint"]
        self._queue_image(name, image, TEXT_ROW_DELAY if is_text else None, base, held)

    def _queue_image(self, name, image, row_delay=None, base=None, held=False):
        job = Job(name, image, preview_png(image), row_delay, base, held)
        self.queue.add(job)
        self._json(201, job.summary())

    def _photo(self, data, name):
        photo = thermal.photo_base(Image.open(io.BytesIO(data)))
        height = round(photo.height * thermal.USB_MAX_DOTS / photo.width)
        base = photo.resize((thermal.USB_MAX_DOTS, height), Image.LANCZOS)
        self.queue.last_photo, self.queue.last_name = base, name
        return adjusted(base, self.queue.settings)

    def _adjust_preview(self, values):
        if self.queue.last_photo is None:
            return self._json(404, {"error": "no photo yet"})
        preview = io.BytesIO()
        adjusted(self.queue.last_photo, clean_settings(values)).convert("1").save(preview, "PNG")
        self._send(200, preview.getvalue(), "image/png")

    def _body(self):
        size = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(min(size, 65536)) or b"{}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.queue = Queue(args.dry_run)
    Handler.port = args.port
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Thermal printer app running at {url} (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
