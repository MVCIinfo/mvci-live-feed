#!/usr/bin/env python3
"""Locally obtain a YouTube OAuth refresh token without third-party packages."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def parse_callback(query: str, expected_state: str):
    params = urllib.parse.parse_qs(query)
    if params.get("state", [None])[0] != expected_state:
        raise ValueError("invalid OAuth state")
    return params.get("code", [None])[0], params.get("error", [None])[0]


class CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None
    expected_state = None
    event = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            code, error = parse_callback(parsed.query, self.expected_state)
        except ValueError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid OAuth state. You can close this tab.")
            return
        type(self).code = code
        type(self).error = error
        self.send_response(200 if type(self).code else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<p>認証が完了しました。このタブを閉じて、ターミナルに戻ってください。</p>".encode())
        self.event.set()

    def log_message(self, format, *args):
        # Default handler logs the request target, which can contain OAuth data.
        return


def main():
    parser = argparse.ArgumentParser(description="Google OAuth refresh tokenをローカルで取得します")
    parser.add_argument("--client-json", required=True, type=Path, help="Google CloudでダウンロードしたデスクトップアプリOAuth JSON")
    parser.add_argument("--output", required=True, type=Path, help="秘密情報を保存するローカルファイル（リポジトリ外）")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    try:
        output.relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass
    else:
        parser.error("出力先はこのリポジトリの外にしてください")
    client_data = json.loads(args.client_json.expanduser().read_text(encoding="utf-8"))
    client = client_data.get("installed") or client_data.get("web")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        parser.error("client JSONにclient_id/client_secretが見つかりません")

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    if "installed" not in client_data:
        parser.error("デスクトップアプリ（installed形式）のOAuth JSONを指定してください")
    CallbackHandler.code = None
    CallbackHandler.error = None
    CallbackHandler.expected_state = state
    from threading import Event
    CallbackHandler.event = Event()
    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    callback = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    params = {
        "client_id": client["client_id"], "redirect_uri": callback,
        "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("ブラウザーでGoogleの同意画面を開きます。アカウントと権限を確認してください。")
    webbrowser.open(url)
    try:
        deadline = __import__("time").monotonic() + 180
        while not CallbackHandler.event.is_set() and __import__("time").monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not CallbackHandler.event.is_set() or not getattr(CallbackHandler, "code", None):
        raise SystemExit("OAuth認証が完了しませんでした。認証をキャンセルしたか、3分でタイムアウトしました。")

    body = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "code": CallbackHandler.code, "code_verifier": verifier,
        "grant_type": "authorization_code", "redirect_uri": callback,
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except Exception:
        raise SystemExit("Googleからトークンを取得できませんでした。設定を確認して再実行してください。") from None
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise SystemExit("refresh tokenが返りませんでした。Googleアカウントのアクセス権を解除して、再実行してください。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "YOUTUBE_CLIENT_ID": client["client_id"],
        "YOUTUBE_CLIENT_SECRET": client["client_secret"],
        "YOUTUBE_REFRESH_TOKEN": refresh,
    }, indent=2), encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass
    print(f"認証情報を指定ファイルに保存しました: {output}")
    print("ファイルの3つの値を、GitHubリポジトリの Settings → Secrets and variables → Actions に同名のRepository secretsとして個別登録してください。値は画面やチャットへ貼らないでください。")


if __name__ == "__main__":
    main()
