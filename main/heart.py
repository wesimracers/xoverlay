# heart
#
# Pulsoid heart-rate poller for the INFO widget.
#
# Discovered protocol (from inspecting the public widget JS bundle):
#   1. POST https://pulsoid.net/v1/api/public/rpc
#         body: {"jsonrpc":"2.0","method":"getWidget",
#                "params":{"widgetId":"<UUID>"},"id":"1"}
#         header: x-rpc-method: getWidget
#      → returns JSON containing `ramielUrl` (the wss:// URL with token baked
#        in) and `token` (separate access_token if needed).
#
#   2. Connect to that wss URL. Pulsoid sends `legacy_json` frames like:
#         {"measured_at": <ms>, "data": {"heart_rate": 78}}
#      We just pluck `data.heart_rate` per frame.
#
# This avoids the OAuth flow entirely — public widgets stamp their own
# read-only token into ramielUrl. The token is harmless to expose since
# anyone visiting the widget URL gets the same one.
#
# Configuration in overlay.json under "heart_settings":
#     {
#       "enabled": true,
#       "widget_url": "https://pulsoid.net/widget/view/{UUID}",
#       "stale_seconds": 30
#     }

from __future__ import annotations

import base64
import hashlib  # 261001_CURSOR
import json
import os
import re
import socket
import ssl
import struct
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import logging
from typing import Optional

# ---- module state -----------------------------------------------------------

_LAST_BPM: Optional[int] = None
_LAST_BPM_T: float = 0.0
_FIRST_BPM_LOGGED = False
_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_LAST_STATUS: str = "idle"        # for logging / debugging
_LAST_RAMIEL_URL: Optional[str] = None
_LAST_RAMIEL_FETCH_T: float = 0.0

_RPC_URL = "https://pulsoid.net/v1/api/public/rpc"
_RAMIEL_REFRESH_SEC = 600.0       # re-fetch the ws URL every 10 minutes

# Match `https://pulsoid.net/widget/view/{UUID}` and extract the UUID.
_WIDGET_ID_RE = re.compile(r"/widget/view/([0-9a-fA-F-]{36})")


def _log(msg: str):
    """Route through core._log when available, else stderr."""
    try:
        import core
        core._log(f"[heart] {msg}")
    except Exception:
        logging.getLogger("heart").info(msg)


def latest_bpm():
    """Return the most recent BPM (int) or None if not available / stale."""
    with _LOCK:
        bpm = _LAST_BPM
        t = _LAST_BPM_T
    if bpm is None or t == 0.0:
        return None
    try:
        import core
        stale = float((core.cfg.get("heart_settings") or {}).get("stale_seconds", 30))
    except Exception:
        stale = 30.0
    if (time.time() - t) > stale:
        return None
    return bpm


def status():
    """Diagnostic — for logging / future debug overlay."""
    return _LAST_STATUS


def _set_bpm(v):
    global _LAST_BPM, _LAST_BPM_T, _FIRST_BPM_LOGGED
    if v is None:
        return
    try:
        v = int(v)
    except Exception:
        return
    if v < 20 or v > 250:    # plausibility guard against parsing junk
        return
    with _LOCK:
        _LAST_BPM = v
        _LAST_BPM_T = time.time()
        first = not _FIRST_BPM_LOGGED
        _FIRST_BPM_LOGGED = True
    if first:
        _log(f"first valid BPM received: {v}")


def _set_status(s):
    global _LAST_STATUS
    _LAST_STATUS = s
    _log(f"status: {s}")


def _extract_widget_id(url):
    if not url:
        return None
    m = _WIDGET_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_bpm_from_text(text):
    """Extract a BPM integer from one Pulsoid text frame.

    Verified live frame format:
        {"timestamp": <ms>, "data": {"heartRate": 63}}
    Earlier docs / other response_modes show:
        {"data": {"heart_rate": NN}}
    Plain-text mode just sends the number alone.

    We accept all three so a future Pulsoid format tweak doesn't silently
    break the widget."""
    if not text:
        return None
    # Try JSON first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            data = obj.get("data") or obj
            if isinstance(data, dict):
                # Try every known key spelling
                for k in ("heartRate", "heart_rate", "bpm", "value"):
                    v = data.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            pass
            # last resort: look for any int-valued field
            for k, v in obj.items():
                try:
                    iv = int(v)
                    if 20 <= iv <= 250:
                        return iv
                except Exception:
                    continue
    except Exception:
        pass
    # plain-text fallback
    try:
        return int(str(text).strip())
    except Exception:
        return None


# ---- 1) JSON-RPC: get the widget config ------------------------------------

def _fetch_ramiel_url(widget_id):
    """Call getWidget and return its `ramielUrl` (the public ws:// URL with
    a read-only access_token baked in). Returns None on failure."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "getWidget",
        "params": {"widgetId": widget_id},
        "id": "1",
    }).encode("utf-8")
    req = urllib.request.Request(
        _RPC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-rpc-method": "getWidget",
            "User-Agent": "Mozilla/5.0 (overlay)",
        },
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _log(f"getWidget RPC failed: {e!r}")
        return None
    result = out.get("result") if isinstance(out, dict) else None
    if not isinstance(result, dict):
        _log(f"getWidget returned no result: {out}")
        return None
    rurl = result.get("ramielUrl")
    if not rurl:
        _log("getWidget result has no ramielUrl — widget may be private/expired")
        return None
    return rurl


# ---- 2) WebSocket loop -----------------------------------------------------
#
# We implement a minimal RFC 6455 client using only stdlib so this works in a
# stock Python install without `pip install websocket-client`. Pulsoid only
# sends short text frames (the JSON `{"data":{"heart_rate":N}}` payload) which
# is the easy subset of the spec. We:
#   - open SSL socket to host:443
#   - send HTTP Upgrade with Sec-WebSocket-Key
#   - read server frames: opcode 0x1 (text), no mask bit (server frames are
#     never masked per RFC), payload length 7-bit / 16-bit (Pulsoid frames
#     are < 1KB so 64-bit length unused).
#   - send periodic pings to keep NAT alive
# The stdlib connection is preferred because it follows the same direct TLS
# path as the public widget. websocket-client remains a fallback for servers
# that need its more complete frame handling.


def _parse_ws_url(ws_url):
    """Return (host, port, path, use_ssl)."""
    p = urllib.parse.urlparse(ws_url)
    use_ssl = (p.scheme == "wss")
    host = p.hostname
    port = p.port or (443 if use_ssl else 80)
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    return host, port, path, use_ssl


def _ws_handshake(sock, host, path):
    """Send HTTP Upgrade and verify the 101 Switching Protocols response."""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"User-Agent: overlay/1.0\r\n"
        f"Origin: https://pulsoid.net\r\n"
        f"\r\n"
    ).encode("ascii")
    sock.sendall(req)

    # Read until \r\n\r\n. The same TCP packet often carries the first
    # websocket frame after the HTTP headers; those bytes must be kept.
    buf = b""
    while b"\r\n\r\n" not in buf:
        if len(buf) > 8192:
            raise ConnectionError("oversized handshake response")
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("server closed during handshake")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    first = head.split(b"\r\n", 1)[0]
    if b"101" not in first:
        raise ConnectionError(f"handshake failed: {first!r}")
    accept = b""  # 261001_CURSOR
    for line in head.split(b"\r\n")[1:]:  # 261001_CURSOR
        if line.lower().startswith(b"sec-websocket-accept:"):  # 261001_CURSOR
            accept = line.split(b":", 1)[1].strip()  # 261001_CURSOR
    expected = base64.b64encode(hashlib.sha1(  # 261001_CURSOR
        key.encode("ascii") + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())  # 261001_CURSOR
    if accept != expected:  # 261001_CURSOR
        raise ConnectionError("websocket accept mismatch")  # 261001_CURSOR
    return rest


class _SocketBuffer:
    """Socket reader that replays bytes already consumed by the handshake."""

    def __init__(self, sock, pending=b""):
        self.sock = sock
        self.pending = pending

    def recv_exact(self, n):
        chunks = []
        have = 0
        if self.pending:
            take = self.pending[:n]
            self.pending = self.pending[len(take):]
            chunks.append(take)
            have = len(take)
        while have < n:
            c = self.sock.recv(n - have)
            if not c:
                raise ConnectionError("ws stream closed")
            chunks.append(c)
            have += len(c)
        return b"".join(chunks)


def _ws_read_frame(stream):
    """Return (fin, opcode, payload) for one RFC 6455 frame. Server frames
    are never masked. We support text/binary/ping/pong/close opcodes; payload
    lengths up to 2^31. Fragmentation: assemble continuation frames into the
    initial opcode."""
    hdr = stream.recv_exact(2)
    b1, b2 = hdr[0], hdr[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    plen = b2 & 0x7F
    if plen == 126:
        plen = struct.unpack("!H", stream.recv_exact(2))[0]
    elif plen == 127:
        plen = struct.unpack("!Q", stream.recv_exact(8))[0]
    if plen > 65536:  # 261001_CURSOR
        raise ConnectionError("ws frame too large")  # 261001_CURSOR
    if masked:
        # Server should never mask; swallow the key just in case
        mask = stream.recv_exact(4)
    else:
        mask = None
    payload = stream.recv_exact(plen) if plen > 0 else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


def _ws_send_frame(sock, opcode, payload=b""):
    """Send a client→server frame. Client frames MUST be masked per RFC."""
    b1 = 0x80 | (opcode & 0x0F)        # FIN=1
    plen = len(payload)
    mask = os.urandom(4)
    if plen < 126:
        hdr = struct.pack("!BB", b1, 0x80 | plen)
    elif plen < (1 << 16):
        hdr = struct.pack("!BBH", b1, 0x80 | 126, plen)
    else:
        hdr = struct.pack("!BBQ", b1, 0x80 | 127, plen)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(hdr + mask + masked)


def _open_tcp_stream(host, port):
    """Try IPv4 first; some networks resolve IPv6 but cannot reach it."""
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses.sort(key=lambda item: item[0] != socket.AF_INET)
    last_error = None
    for family, socktype, proto, _, sockaddr in addresses:
        raw = socket.socket(family, socktype, proto)
        raw.settimeout(8)
        try:
            raw.connect(sockaddr)
            return raw
        except OSError as e:
            last_error = e
            raw.close()
    raise last_error or OSError("no stream address available")


def _ws_loop_stdlib(ws_url, timeout_per_recv=30.0):
    """Read frames from a Pulsoid websocket using stdlib only. Blocks until
    the socket closes or an error happens. Returns True if at least one
    heart_rate frame was received."""
    host, port, path, use_ssl = _parse_ws_url(ws_url)
    raw = _open_tcp_stream(host, port)
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(raw, server_hostname=host)
        else:
            sock = raw
        stream = _SocketBuffer(sock, _ws_handshake(sock, host, path))
        sock.settimeout(timeout_per_recv)
        _set_status("connected")

        got = [False]
        last_ping = time.time()
        # Buffer to handle fragmented text messages
        msg_buf = bytearray()
        msg_op = None

        while not _STOP.is_set():
            try:
                fin, opcode, payload = _ws_read_frame(stream)
            except socket.timeout:
                # send a ping to keep the connection alive
                if time.time() - last_ping > 25:
                    try:
                        _ws_send_frame(sock, 0x9, b"")  # ping
                        last_ping = time.time()
                    except Exception:
                        break
                continue

            if opcode == 0x8:    # close
                break
            if opcode == 0x9:    # ping → pong
                _ws_send_frame(sock, 0xA, payload)
                continue
            if opcode == 0xA:    # pong
                continue

            if opcode in (0x1, 0x2):
                msg_buf = bytearray(payload)
                msg_op = opcode
            elif opcode == 0x0:
                msg_buf.extend(payload)

            if not fin:
                continue

            # End of message — decode
            if msg_op == 0x1:
                try:
                    text = bytes(msg_buf).decode("utf-8", errors="replace")
                except Exception:
                    text = ""
                # Pulsoid sends:
                #   {"timestamp":...,"data":{"heartRate":63}}
                # Some response_modes / older docs use snake_case
                # ({"data":{"heart_rate":N}}) — accept both. Verified live
                # against the public widget endpoint: camelCase is what
                # actually arrives on the wire today.
                hr = _parse_bpm_from_text(text)
                if hr is not None:
                    _set_bpm(hr)
                    got[0] = True
            msg_buf.clear()
            msg_op = None
        return got[0]
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            raw.close()
        except Exception:
            pass


def _try_websocket(ws_url):
    """One connection attempt, using the direct stdlib client first."""
    try:
        ok = _ws_loop_stdlib(ws_url)
        if ok or _STOP.is_set():
            return ok
        _set_status("ws stdlib loop ended without BPM; trying websocket-client")
    except Exception as e:
        _set_status(f"ws stdlib loop failed: {e!r}; trying websocket-client")

    # --- fallback: websocket-client (when installed) ---
    try:
        import websocket  # type: ignore
        got = [False]

        def on_open(ws):
            _set_status("connected (websocket-client)")

        def on_message(ws, message):
            hr = _parse_bpm_from_text(message)
            if hr is not None:
                _set_bpm(hr)
                got[0] = True

        def on_error(ws, err):
            _set_status(f"ws error: {err!r}")

        def on_close(ws, code, reason):
            _set_status(f"ws closed code={code} reason={reason}")

        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever(ping_interval=20, ping_timeout=10)
        return got[0]
    except ImportError:
        return False
    except Exception as e:
        _set_status(f"websocket-client failed: {e!r}")
        return False


# ---- worker thread ---------------------------------------------------------

def _worker():
    global _LAST_RAMIEL_URL, _LAST_RAMIEL_FETCH_T
    backoff = 2.0

    while not _STOP.is_set():
        try:
            import core
            settings = core.cfg.get("heart_settings") or {}
        except Exception:
            settings = {}

        if not settings.get("enabled", True):
            _set_status("disabled in config")
            time.sleep(2.0)
            continue

        wurl = settings.get("widget_url") or ""
        wid = _extract_widget_id(wurl)
        if not wid:
            _set_status(f"could not extract widget UUID from: {wurl!r}")
            time.sleep(10.0)
            continue

        # Refresh ramielUrl periodically (the access_token can rotate).
        now = time.time()
        if (not _LAST_RAMIEL_URL) or (now - _LAST_RAMIEL_FETCH_T) > _RAMIEL_REFRESH_SEC:
            _set_status(f"resolving ramielUrl for widget {wid}")
            ru = _fetch_ramiel_url(wid)
            if ru:
                _LAST_RAMIEL_URL = ru
                _LAST_RAMIEL_FETCH_T = now
                _set_status("ramielUrl ok")
            else:
                _set_status("ramielUrl fetch failed — backing off")
                time.sleep(min(backoff, 60.0))
                backoff = min(backoff * 1.5, 60.0)
                continue

        ok = _try_websocket(_LAST_RAMIEL_URL)
        if ok:
            backoff = 2.0
            time.sleep(0.5)
        else:
            # Force ramielUrl re-fetch on next iter — token may have expired.
            _LAST_RAMIEL_URL = None
            time.sleep(min(backoff, 60.0))
            backoff = min(backoff * 1.5, 60.0)


def start():
    """Launch the background heart-rate worker (idempotent)."""
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_worker, name="heart-rate-worker", daemon=True)
    _THREAD.start()


def stop():
    _STOP.set()
