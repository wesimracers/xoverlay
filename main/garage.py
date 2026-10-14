# garage
#
# Garage-cover widget.
#
# Shows a solid-color block on the OBS overlay whenever the player is in the
# iRacing garage / out of the cockpit. The intent (per user request, modeled
# on irDashies' equivalent feature) is to hide setup-page details from stream
# viewers — when the driver pops the helmet and edits ride height / wing /
# fuel, the audience just sees a neutral cover, not the proprietary numbers.
#
# Detection
# ---------
# Use IsGarageVisible as the primary trigger. This telemetry flag is True
# only when the Garage Setup window itself is open/visible. That is exactly
# the stream-protection condition the user asked for.
#
# We defensively check IsOnTrack — if True we are not covering.
#
# Visibility rule (opposite of normal widgets)
# --------------------------------------------
# BaseWin's default rule is "show ONLY while driving on track" — exactly the
# wrong rule for this widget, which should show ONLY while in the garage.
# We override _should_be_visible() to invert the logic. The global
# `show_in_garage` flag is ignored — for this widget, being in garage IS
# the trigger condition.

from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QTimer
import traceback
import time
import json
import threading
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import core
from base import BaseWin, parse_hex_color as _parse_color  # 261001_CURSOR


# def _parse_color(val, default):
#     """Accept '#RRGGBB' hex strings or fall back to the supplied default."""
#     try:
#         if isinstance(val, str):
#             s = val.strip()
#             if s.startswith("#") and len(s) == 7:
#                 r = int(s[1:3], 16)
#                 g = int(s[3:5], 16)
#                 b = int(s[5:7], 16)
#                 return QColor(r, g, b)
#     except Exception:
#         pass
#     return default


def _tele_bool(val, default=False):
    """Parse iRacing telemetry bool robustly (scalar, list, int, string)."""
    try:
        if val is None:
            return bool(default)
        if isinstance(val, (list, tuple)):
            if not val:
                return bool(default)
            val = val[0]
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off", ""):
                return False
        return bool(val)
    except Exception:
        return bool(default)


_OBS_DEFAULT_URL = "http://127.0.0.1:8765/garage-cover"
_OBS_STATE_LOCK = threading.Lock()
_OBS_STATE = {
    "show": False,
    "bg": "#101010",
    "fg": "#FFFFFF",
    "label": "GARAGE",
    "show_label": True,
}
_OBS_SERVER = {
    "server": None,
    "thread": None,
    "host": "127.0.0.1",
    "port": 8765,
    "path": "/garage-cover",
}


def _norm_obs_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return "/garage-cover"
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/garage-cover"


def _parse_obs_url(u: str):
    try:
        pu = urlparse((u or "").strip())
        if pu.scheme not in ("http", ""):
            return ("127.0.0.1", 8765, "/garage-cover")
        host = (pu.hostname or "127.0.0.1").strip()
        port = int(pu.port or 8765)
        path = _norm_obs_path(pu.path or "/garage-cover")
        return (host, port, path)
    except Exception:
        return ("127.0.0.1", 8765, "/garage-cover")


def _build_obs_url(host: str, port: int, path: str) -> str:
    return f"http://{host}:{int(port)}{_norm_obs_path(path)}"


def _set_obs_state(*, show=None, bg=None, fg=None, label=None, show_label=None):
    with _OBS_STATE_LOCK:
        if show is not None:
            _OBS_STATE["show"] = bool(show)
        if bg is not None:
            _OBS_STATE["bg"] = str(bg)
        if fg is not None:
            _OBS_STATE["fg"] = str(fg)
        if label is not None:
            _OBS_STATE["label"] = str(label)
        if show_label is not None:
            _OBS_STATE["show_label"] = bool(show_label)


def _obs_html(base_path: str) -> str:
    p = _norm_obs_path(base_path)
    state_path = f"{p}/state"
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      background: transparent;
      overflow: hidden;
    }}
    #cover {{
      position: absolute;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: #101010;
      color: #ffffff;
      font-family: Consolas, Arial, sans-serif;
      font-weight: 700;
      font-size: min(12vw, 140px);
      user-select: none;
    }}
  </style>
</head>
<body>
  <div id="cover"></div>
  <script>
    const cover = document.getElementById("cover");
    async function tick() {{
      try {{
        const r = await fetch("{state_path}?t=" + Date.now(), {{ cache: "no-store" }});
        const s = await r.json();
        if (s.show) {{
          cover.style.display = "flex";
          cover.style.background = s.bg || "#101010";
          cover.style.color = s.fg || "#ffffff";
          cover.textContent = s.show_label ? (s.label || "GARAGE") : "";
        }} else {{
          cover.style.display = "none";
          cover.textContent = "";
        }}
      }} catch (_e) {{
        cover.style.display = "none";
      }}
    }}
    setInterval(tick, 150);
    tick();
  </script>
</body>
</html>"""


def _make_obs_handler():
    class _ObsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            p = _norm_obs_path(_OBS_SERVER.get("path", "/garage-cover"))
            if self.path == p or self.path.startswith(p + "?") or self.path == p + "/":
                payload = _obs_html(p).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if self.path == (p + "/state") or self.path.startswith((p + "/state?")):
                with _OBS_STATE_LOCK:
                    data = dict(_OBS_STATE)
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, _fmt, *_args):
            return

    return _ObsHandler


def _ensure_obs_server(url: str):
    host, port, path = _parse_obs_url(url)
    if str(host).strip().lower() not in ("127.0.0.1", "localhost", "::1"):  # 261001_CURSOR
        core._log(f"Garage OBS host {host!r} is not loopback; using 127.0.0.1")  # 261001_CURSOR
        host = "127.0.0.1"  # 261001_CURSOR
    _OBS_SERVER["host"] = host
    _OBS_SERVER["port"] = port
    _OBS_SERVER["path"] = path

    if _OBS_SERVER["server"] is not None:
        return _build_obs_url(host, port, path)

    try:
        handler = _make_obs_handler()
        srv = ThreadingHTTPServer((host, port), handler)
        th = threading.Thread(target=srv.serve_forever, daemon=True, name="garage-obs-http")
        th.start()
        _OBS_SERVER["server"] = srv
        _OBS_SERVER["thread"] = th
        core._log(f"Garage OBS endpoint started: {_build_obs_url(host, port, path)}")
    except Exception as ex:
        core._log(f"Garage OBS endpoint failed: {ex!r}")
    return _build_obs_url(host, port, path)


class GarageCover(BaseWin):
    """Solid block that appears whenever the player is in the garage UI."""

    def __init__(self):
        super().__init__("garage")
        s = core.cfg.get("garage_settings") or {}
        _obs_url_raw = str(s.get("obs_url", "") or "").strip()
        if (not _obs_url_raw) or ("dummyimage.com" in _obs_url_raw.lower()):
            _obs_url_raw = _OBS_DEFAULT_URL
            try:
                core.cfg.setdefault("garage_settings", {})["obs_url"] = _obs_url_raw
                core.save_cfg()
            except Exception:
                pass
        self._obs_url = _ensure_obs_server(_obs_url_raw)
        self._bg_color = _parse_color(s.get("bg_color", "#101010"), QColor(16, 16, 16))
        self._fg_color = _parse_color(s.get("fg_color", "#FFFFFF"), QColor(255, 255, 255))
        self._label    = str(s.get("label", "GARAGE"))
        self._show_label = bool(s.get("show_label", True))
        _set_obs_state(
            show=False,
            bg=self._bg_color.name(),
            fg=self._fg_color.name(),
            label=self._label,
            show_label=self._show_label,
        )
        # iRacing can briefly flicker IsGarageVisible during transitions.
        # Keep cover visible for a short tail to prevent visual flashing.
        self._hide_delay_s = 0.50
        self._last_setup_visible_t = 0.0
        self._latched_visible = False

        # Paint timer — drives both the visibility re-check (handled by
        # BaseWin's _vis_timer) and the periodic repaint. 250 ms is plenty
        # for what is essentially a static block.
        # self._timer = QTimer(self)
        # self._timer.timeout.connect(self.update_data)
        # self._timer.start(int(s.get("update_ms", 250)))
        self._timer = None  # 261001_CURSOR

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    def apply_settings(self, s: dict):
        """Live-refresh appearance after the manager saves config."""
        try:
            _obs_url_raw = str(s.get("obs_url", self._obs_url) or "").strip()
            if _obs_url_raw:
                self._obs_url = _ensure_obs_server(_obs_url_raw)
                try:
                    core.cfg.setdefault("garage_settings", {})["obs_url"] = self._obs_url
                except Exception:
                    pass
            self._bg_color = _parse_color(s.get("bg_color", "#101010"), self._bg_color)
            self._fg_color = _parse_color(s.get("fg_color", "#FFFFFF"), self._fg_color)
            self._label    = str(s.get("label", self._label))
            self._show_label = bool(s.get("show_label", True))
            _set_obs_state(
                bg=self._bg_color.name(),
                fg=self._fg_color.name(),
                label=self._label,
                show_label=self._show_label,
            )
            if self._timer:
                self._timer.setInterval(int(s.get("update_ms", 250)))
            self.update()
        except Exception:
            pass

    def _should_be_visible(self):
        # Manager ON/OFF toggle still wins.
        try:
            wcfg = (core.cfg.get("windows") or {}).get(self._key, {})
            if not wcfg.get("enabled", True):
                _set_obs_state(show=False)
                return False
        except Exception:
            pass
        # Need a live iRacing connection.
        try:
            if not getattr(core, "ir", None) or not core.ir.is_connected:
                _set_obs_state(show=False)
                return False
        except Exception:
            _set_obs_state(show=False)
            return False

        try:
            garage_visible = _tele_bool(core.sg("IsGarageVisible", False), False)
            on_track  = _tele_bool(core.sg("IsOnTrack", False), False)
        except Exception:
            _set_obs_state(show=False)
            return False

        # If we're actively on track, never cover.
        if on_track:
            self._latched_visible = False
            _set_obs_state(show=False)
            return False

        now = time.monotonic()

        # Strict trigger: actual Garage Setup panel visible only.
        # Browser-only mode: publish show/hide state to OBS endpoint, but
        # keep this local Qt window hidden so setup remains editable.
        if garage_visible:
            self._last_setup_visible_t = now
            self._latched_visible = True
            _set_obs_state(show=True)
            return False

        # Brief hold to avoid flash-off during telemetry tick jitter.
        if self._latched_visible and (now - self._last_setup_visible_t) <= self._hide_delay_s:
            _set_obs_state(show=True)
            return False

        self._latched_visible = False
        _set_obs_state(show=False)
        return False

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            # Solid fill — the entire point of this widget. Anything peeking
            # through would defeat the purpose of hiding setup info.
            p.fillRect(self.rect(), self._bg_color)

            if self._show_label and self._label:
                # Scale label down to fit; bias toward a noticeable size so
                # viewers immediately understand "this is intentional, not
                # a glitch". Floor at 14 pt for very small cover blocks.
                f = QFont(self.font_bold)
                f.setPointSize(max(14, int(self.height() * 0.30)))
                f.setBold(True)
                p.setFont(f)
                p.setPen(self._fg_color)
                p.drawText(self.rect(),
                           Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                           self._label)
        except Exception as ex:
            core._log(f"Garage cover paint error: {ex!r}")
            core._log(traceback.format_exc())


# if correct reply yes, else return solutions that are mandatory to work
