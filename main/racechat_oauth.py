"""Interactive OAuth: invoked only from authorization buttons, no secrets in logs."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from racechat_service import ServiceError

GOOGLE_REDIRECT = "http://127.0.0.1:18765/"
TWITCH_SCOPES = "user:read:chat user:write:chat"


class LoopbackServer(HTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


def form_post(url, data, pending=False):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except ValueError:
            payload = {}
        code = payload.get("error") or payload.get("message")
        if pending and code in ("authorization_pending", "slow_down"):
            return {"pending": code}
        raise ServiceError(f"OAuth HTTP {exc.code}: authorization denied or expired, or the app is misconfigured.",
                           fatal=exc.code in (400, 401, 403), status=exc.code) from None
    except (OSError, ValueError):
        raise ServiceError("OAuth: network failure. Try authorizing again.") from None


def twitch_device(client_id, emit, stop):
    if not client_id:
        raise ServiceError("Save the Client ID of a public Twitch app first.")
    data = form_post("https://id.twitch.tv/oauth2/device", {"client_id": client_id, "scopes": TWITCH_SCOPES})
    uri = data["verification_uri"]
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "https" or parsed.hostname != "www.twitch.tv" or parsed.path != "/activate":
        raise ServiceError("Twitch returned an unexpected authorization URL.")
    emit("oauth_browser", uri)
    emit("status", "Twitch: authorize in the browser. Code: " + data["user_code"])
    deadline = time.monotonic() + min(int(data["expires_in"]), 1800)
    interval = max(5, int(data.get("interval", 5)))
    while time.monotonic() < deadline and not stop.wait(interval):
        result = form_post("https://id.twitch.tv/oauth2/token", {
            "client_id": client_id, "device_code": data["device_code"], "scopes": TWITCH_SCOPES,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, pending=True)
        if result.get("pending") == "slow_down":
            interval += 5
        elif not result.get("pending"):
            return token_fields("twitch", result)
    raise ServiceError("Twitch authorization was canceled or expired.")


def google_desktop(client, emit, stop):
    client_id, client_secret = client.get("client_id"), client.get("client_secret")
    if not client_id or not client_secret:
        raise ServiceError("Import a Google OAuth JSON file for a Desktop app.")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            valid = parsed.path == "/" and secrets.compare_digest(query.get("state", [""])[0], state)
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if valid:
                result.update(code=query.get("code", [""])[0], error=query.get("error", [""])[0])
                self.wfile.write("Authorization received. You can close this window and return to Overlay.".encode())
            else:
                self.wfile.write(b"Invalid authorization request.")

    # Bind before opening the browser; never listen on external interfaces.
    try:
        server = LoopbackServer(("127.0.0.1", 18765), Handler)
    except OSError:
        raise ServiceError("Local port 18765 is in use. Close the other authorization and try again.") from None
    with server:
        server.timeout = .5
        emit("oauth_browser", "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": GOOGLE_REDIRECT, "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.force-ssl", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "consent", "access_type": "offline"}))
        deadline = time.monotonic() + 180
        while not result and not stop.is_set() and time.monotonic() < deadline:
            server.handle_request()
    if stop.is_set() or not result.get("code") or result.get("error"):
        raise ServiceError("Google authorization was canceled, denied, or expired.")
    data = form_post("https://oauth2.googleapis.com/token", {
        "client_id": client_id, "client_secret": client_secret, "code": result["code"],
        "code_verifier": verifier, "redirect_uri": GOOGLE_REDIRECT, "grant_type": "authorization_code"})
    return token_fields("youtube", data)


def token_fields(provider, data):
    result = {provider + "_token": data["access_token"]}
    if data.get("refresh_token"):
        result[provider + "_refresh_token"] = data["refresh_token"]
    return result


def refresh_tokens(provider, config, credentials):
    refresh = credentials.get(provider + "_refresh_token")
    if not refresh:
        raise ServiceError("Authorization expired; authorize again in the browser.", fatal=True)
    data = {"grant_type": "refresh_token", "refresh_token": refresh}
    if provider == "twitch":
        data["client_id"] = config["twitch_client_id"]
        url = "https://id.twitch.tv/oauth2/token"
    elif provider == "youtube":
        client = json.loads(credentials.get("google_client_json", "{}"))
        if not client.get("client_id") or not client.get("client_secret"):
            raise ServiceError("Google client is missing; import the Desktop JSON file.", fatal=True)
        data.update(client_id=client["client_id"], client_secret=client["client_secret"])
        url = "https://oauth2.googleapis.com/token"
    else:
        raise ServiceError("Invalid OAuth provider.", fatal=True)
    return token_fields(provider, form_post(url, data))
