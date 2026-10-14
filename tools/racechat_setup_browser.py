"""Temporary loopback-only setup form, for configuring Race Chat without desktop focus.

No remote UI automation, cookies, account discovery or secret logging. Browser actions
are performed by the user/connected Browser Use. Run explicitly; expires after 30 min.
"""
import html
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from racechat_store import Store
from racechat_oauth import LoopbackServer, google_desktop, twitch_device
from racechat_service import request, ServiceError

store = Store()
config, credentials = store.load(), store.secrets()
session = secrets.token_urlsafe(32)
stop = threading.Event()
status, auth_url, auth_busy = "Configuração local. Nenhuma conta ligada automaticamente.", "", False
lock = threading.Lock()


def oauth(provider="Google"):
    global status, auth_url, auth_busy
    def emit(kind, value):
        global auth_url, status
        if kind == "oauth_browser":
            auth_url = value
            status = f"Abra a autorização {provider} abaixo."
    try:
        if provider == "Twitch":
            tokens = twitch_device(config["twitch_client_id"], emit, stop)
        else:
            client = json.loads(credentials.get("google_client_json", "{}"))
            tokens = google_desktop(client, emit, stop)
        with lock:
            credentials.update(tokens)
            store.save(config, credentials)
        status = f"{provider} autorizado. Token guardado com DPAPI."
    except Exception as exc:
        status = str(exc) if isinstance(exc, ServiceError) else "Autorização falhou; verifique cliente local."
    finally:
        auth_url, auth_busy = "", False


def validate():
    global status
    reports = []
    try:
        if credentials.get("twitch_token"):
            data = request("https://id.twitch.tv/oauth2/validate", "OAuth " + credentials["twitch_token"])
            if data.get("client_id") != config["twitch_client_id"]:
                raise ServiceError("Twitch: token pertence a outro Client ID.")
            reports.append("Twitch autorizado: " + data.get("login", "") + "; scopes: " + ", ".join(data.get("scopes", [])))
        if credentials.get("youtube_token"):
            data = request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", "Bearer " + credentials["youtube_token"])
            reports.append("YouTube autorizado: " + ", ".join(i["snippet"]["title"] for i in data.get("items", [])))
        if credentials.get("discord_token"):
            user = request("https://discord.com/api/v10/users/@me", "Bot " + credentials["discord_token"])
            reports.append("Bot Discord válido: " + user["username"])
            guilds = request("https://discord.com/api/v10/users/@me/guilds", "Bot " + credentials["discord_token"])
            reports.append("Servidores: " + ", ".join(g["name"] + " (" + g["id"] + ")" for g in guilds))
        status = " | ".join(reports) or "Ainda não há tokens para validar."
    except ServiceError as exc:
        status = str(exc)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def valid(self):
        expected = "127.0.0.1:" + str(self.server.server_port)
        return self.path == "/" + session and self.headers.get("Host") == expected

    def page(self):
        esc = html.escape
        fields = "".join(f'<label>{esc(label)}<input name="{name}" type="{kind}" autocomplete="off"></label>' for name, label, kind in (
            ("discord_token", "Token do bot Discord (vazio mantém)", "password"),
            ("google_id", "Google Desktop Client ID", "text"), ("google_secret", "Google Desktop Client Secret (vazio mantém)", "password"),
            ("openai_key", "OpenAI API key (vazio mantém)", "password")))
        fields += "".join(f'<label>{esc(name)}<input name="{name}" value="{esc(str(config[name]))}"></label>' for name in (
            "discord_channels", "twitch_client_id", "twitch_channel", "youtube_video"))
        present = ", ".join(key for key in ("discord_token", "twitch_token", "google_client_json", "youtube_token", "openai_key") if credentials.get(key)) or "nenhuma"
        link = f'<p><a href="{esc(auth_url)}" target="_blank" rel="noreferrer">Continuar autorização</a></p>' if auth_url else ""
        return f'''<!doctype html><meta charset="utf-8"><title>Overlay Race Chat — configuração local</title>
        <style>body{{max-width:760px;margin:30px auto;background:#171c25;color:white;font:16px system-ui}}label{{display:block;margin:12px 0}}input{{display:block;width:95%;padding:8px}}button{{padding:10px;margin:6px}}</style>
        <h1>Overlay Race Chat — configuração local</h1><p>{esc(status)}</p><p>Credenciais guardadas: {esc(present)}</p>
        {link}<form method="post" autocomplete="off"><input type="hidden" name="csrf" value="{session}">{fields}
        <button name="action" value="save">Guardar localmente</button><button name="action" value="google">Iniciar OAuth Google</button>
        <button name="action" value="twitch">Iniciar OAuth Twitch</button>
        <button name="action" value="validate">Validar contas (somente leitura)</button><button name="action" value="stop">Encerrar configuração</button></form>
        <p>DPAPI do utilizador Windows. Nenhum token exibido ou enviado ao chat. Esta página não publica mensagens, não grava áudio e não abre janelas desktop.</p>'''.encode()

    def do_GET(self):
        if not self.valid():
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(self.page())

    def do_POST(self):
        global status, auth_busy, auth_url
        origin = self.headers.get("Origin")
        same_origin = origin == f"http://127.0.0.1:{self.server.server_port}"
        # Chromium can serialize Origin as null with no-referrer on local forms.
        same_origin = same_origin or (origin in (None, "null") and self.headers.get("Sec-Fetch-Site") == "same-origin")
        if not self.valid() or not same_origin:
            self.send_error(403); return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_error(400); return
        if not 0 < length <= 16384:
            self.send_error(413); return
        data = urllib.parse.parse_qs(self.rfile.read(length).decode())
        val = lambda k: data.get(k, [""])[0].strip()
        if not secrets.compare_digest(val("csrf"), session):
            self.send_error(403); return
        action = val("action")
        try:
            if action == "save":
                with lock:
                    for key in ("discord_channels", "twitch_client_id", "twitch_channel", "youtube_video"):
                        config[key] = val(key)
                    for key in ("discord_token", "openai_key"):
                        if val(key):
                            credentials[key] = val(key)
                    if val("google_id") and val("google_secret"):
                        credentials["google_client_json"] = json.dumps({"client_id": val("google_id"), "client_secret": val("google_secret")})
                    store.save(config, credentials)
                status = "Guardado com DPAPI; campos secretos limpos."
            elif action in ("google", "twitch") and not auth_busy:
                auth_busy = True
                threading.Thread(target=oauth, args=("Twitch" if action == "twitch" else "Google",), daemon=True).start()
            elif action == "validate":
                threading.Thread(target=validate, daemon=True).start()
            elif action == "stop":
                stop.set()
        except Exception:
            status = "Não foi possível concluir a operação local."
        self.send_response(303); self.send_header("Location", "/" + session); self.end_headers()


if __name__ == "__main__":
    with LoopbackServer(("127.0.0.1", 18766), Handler) as server:
        server.timeout = .5
        print(f"Local setup URL: http://127.0.0.1:18766/{session}", flush=True)
        deadline = time.monotonic() + 1800
        while not stop.is_set() and time.monotonic() < deadline:
            server.handle_request()
        stop.set()
