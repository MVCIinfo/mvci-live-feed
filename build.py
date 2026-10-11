#!/usr/bin/env python3
"""Build a static latest-video page from public YouTube channel RSS feeds."""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from youtube_api import YouTubeAPI, credentials_available, credentials_present, sync_playlist, YOUTUBE_API_ERROR_REASONS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site"
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
NS = {"a": ATOM, "yt": YT}
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1, 3)


class ChannelFetchError(RuntimeError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


class AllChannelsUnavailable(RuntimeError):
    pass


def parse_feed(data: bytes, channel: dict) -> list[dict]:
    root = ET.fromstring(data)
    if root.tag != f"{{{ATOM}}}feed":
        raise ET.ParseError("unexpected RSS root element")
    videos = []
    for entry in root.findall("a:entry", NS):
        title = entry.findtext("a:title", default="", namespaces=NS).strip()
        video_id = entry.findtext("yt:videoId", default="", namespaces=NS).strip()
        published = entry.findtext("a:published", default="", namespaces=NS).strip()
        if not title or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not published:
            continue
        try:
            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        videos.append({"title": title, "video_id": video_id, "published": published_dt.astimezone(timezone.utc),
                       "channel": channel["name"], "channel_id": channel["id"],
                       "url": "https://www.youtube.com/watch?v=" + video_id})
    return videos


def fetch_channel(channel: dict, opener=urllib.request.urlopen, sleeper=time.sleep) -> list[dict]:
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel["id"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MVCILiveFeed/1.0)"})
    for attempt in range(3):
        try:
            with opener(req, timeout=20) as response:
                return parse_feed(response.read(), channel)
        except urllib.error.HTTPError as exc:
            if exc.code in TRANSIENT_HTTP_STATUSES and attempt < 2:
                sleeper(RETRY_DELAYS[attempt])
                continue
            raise ChannelFetchError(f"HTTP_{exc.code}") from None
        except ET.ParseError:
            raise ChannelFetchError("XML_PARSE_ERROR") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < 2:
                sleeper(RETRY_DELAYS[attempt])
                continue
            raise ChannelFetchError("NETWORK_ERROR") from None
    raise ChannelFetchError("NETWORK_ERROR")


def rss_error_category(exc: Exception) -> str:
    if isinstance(exc, ChannelFetchError):
        return exc.category
    if isinstance(exc, ET.ParseError):
        return "XML_PARSE_ERROR"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP_{exc.code}"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "NETWORK_ERROR"
    return "RSS_FETCH_ERROR"


def api_error_category(exc: Exception) -> str:
    # Extract only a numeric HTTP status or an explicitly allowlisted reason.
    message = str(exc)
    match = re.search(r"YouTube API HTTP (\d+) \(([A-Za-z0-9]+)\)", message)
    if match and match.group(2) in YOUTUBE_API_ERROR_REASONS:
        return f"API_HTTP_{match.group(1)}_{match.group(2)}"
    match = re.search(r"YouTube API returned HTTP (\d+)", message)
    if match:
        return f"API_HTTP_{match.group(1)}"
    match = re.search(r"OAuth refresh failed: (invalid_grant|invalid_client|unauthorized_client|access_denied|invalid_request)", message)
    if match:
        return "OAUTH_" + match.group(1)
    if message == "API_CHANNEL_NOT_FOUND":
        return "API_CHANNEL_NOT_FOUND"
    if message == "API_UPLOADS_PLAYLIST_UNAVAILABLE":
        return "API_UPLOADS_PLAYLIST_UNAVAILABLE"
    return "API_FALLBACK_ERROR"


def live_label(live_state: bool | None) -> str:
    if live_state is True:
        return "配信中！"
    if live_state is False:
        return "直近のMVCI配信"
    return "配信状態を確認できません"


def generate_html(video: dict | None, warnings: list[str], config: dict, live_state: bool | None = None, generated: datetime | None = None, playlist_configured: bool = False) -> str:
    title = html.escape(config.get("title", "MVCI 最新動画"))
    enabled = "、".join(html.escape(c["name"]) for c in config.get("channels", []) if c.get("enabled") and c.get("id"))
    notice = "YouTube情報を確認しました。MVCI関連タイトルの最新動画を表示しています。" if video else "現在、MVCI関連タイトルの動画は見つかりませんでした。"
    if warnings:
        notice += " 取得経路の変更または取得できないチャンネルがあります。"
    if not playlist_configured:
        notice += " YouTube連携未設定のため、ライブ確認とプレイリスト同期は無効です。"
    if video:
        title_text = html.escape(video["title"])
        jst = timezone(timedelta(hours=9))
        detail = html.escape(video["channel"]) + " ・ 公開日時 " + html.escape(video["published"].astimezone(jst).strftime("%Y-%m-%d %H:%M JST"))
        updated = "" if generated is None else " ・ 更新 " + html.escape(generated.astimezone(jst).strftime("%Y-%m-%d %H:%M JST"))
        badge = html.escape(live_label(live_state))
        content = f'<p class="badge">{badge}</p><div class="player"><iframe src="https://www.youtube-nocookie.com/embed/{html.escape(video["video_id"], quote=True)}" title="{title_text}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe></div><h2>{title_text}</h2><p>{detail}{updated}</p><p><a href="{html.escape(video["url"], quote=True)}">YouTubeで開く</a></p>'
    else:
        content = '<p class="empty">該当動画が見つかったら、ここに表示されます。</p>'
    warn_html = "" if not warnings else "<details><summary>取得状況</summary><ul>" + "".join("<li>" + html.escape(w) + "</li>" for w in warnings) + "</ul></details>"
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="YouTubeのチャンネルRSSからMVCI関連の最新動画を表示します"><title>{title}</title><style>
:root{{color-scheme:dark;--bg:#10131b;--panel:#1a2030;--text:#f5f7fb;--muted:#aeb8cc;--accent:#70d7bd}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at top,#26324a,var(--bg) 60%);color:var(--text);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(920px,100%);margin:auto;padding:clamp(20px,5vw,52px)}}header{{margin-bottom:26px}}h1{{font-size:clamp(1.7rem,5vw,2.6rem);margin:0 0 8px}}p{{color:var(--muted)}}.card{{background:var(--panel);border:1px solid #344057;border-radius:18px;padding:clamp(16px,4vw,30px);box-shadow:0 18px 55px #0005}}.badge{{display:inline-block;background:#263e4a;color:#8ff0d3;border-radius:999px;padding:4px 12px;font-weight:700;margin:0 0 14px}}.player{{position:relative;aspect-ratio:16/9;background:#080a10;border-radius:12px;overflow:hidden}}iframe{{position:absolute;width:100%;height:100%;border:0}}h2{{font-size:clamp(1.15rem,4vw,1.7rem);line-height:1.4;margin:22px 0 0}}a{{color:var(--accent)}}.status{{border-left:3px solid var(--accent);padding:2px 14px;margin:0 0 20px}}.empty{{padding:40px 10px;text-align:center}}small,footer{{color:var(--muted)}}details{{margin-top:18px;color:var(--muted)}}footer{{margin-top:24px;font-size:.9rem}}</style></head><body><main><header><h1>{title}</h1><p>登録チャンネルの動画からMVCI関連タイトルの最新の1本を表示します。対象: {enabled or "未設定"}</p></header><section class="card"><p class="status">{html.escape(notice)}</p>{content}{warn_html}</section><footer><p>ページ見出しは「配信情報」です。表示中動画は対象チャンネルから見つかった最新のMVCI関連動画です。RSSの公開日時は配信開始時刻とは限りません。配信状態はYouTube Data APIで確認できた場合のみ「配信中！」と表示します。15分間隔の定期更新は即時反映を保証しません。</p><p><a href="feed.xml">RSSフィード</a> ・ <a href="latest.json">JSON</a></p></footer></main></body></html>'''


def rss_feed(video: dict | None, config: dict, generated: datetime, live_state: bool | None = None) -> bytes:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = config.get("title", "MVCI 最新動画")
    ET.SubElement(channel, "link").text = config.get("site_url", "https://MVCIinfo.github.io/mvci-live-feed/")
    ET.SubElement(channel, "description").text = "登録チャンネルからMVCI関連の最新動画を表示するフィードです。"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    if video:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{live_label(live_state)}｜{video['title']}"
        ET.SubElement(item, "link").text = video["url"]
        ET.SubElement(item, "guid", isPermaLink="true").text = video["url"]
        ET.SubElement(item, "pubDate").text = format_datetime(video["published"])
        ET.SubElement(item, "description").text = f"{video['channel']} — YouTube RSSの公開日時です。ライブ開始時刻ではありません。配信状態: {live_label(live_state)}"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def build(config_path: Path = ROOT / "config.json", output_dir: Path = OUT, fetcher=fetch_channel,
          api_factory=YouTubeAPI, env=os.environ) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    channels = [c for c in config.get("channels", []) if c.get("enabled") and c.get("id")]
    videos, warnings = [], []
    sources, failed_channels = [], []
    if not channels:
        raise RuntimeError("有効なチャンネルIDがありません。config.jsonを確認してください。")
    if credentials_present(env) and not credentials_available(env):
        raise RuntimeError("YouTube OAuth credentials are incomplete; provide all three GitHub secrets")
    api = api_factory(env=env) if credentials_available(env) else None
    for c in channels:
        try:
            channel_videos = fetcher(c)
            videos.extend(channel_videos)
            sources.append({"name": c["name"], "channel_id": c["id"], "source": "youtube_channel_rss", "status": "ok", "video_count": len(channel_videos)})
        except Exception as rss_exc:
            rss_category = rss_error_category(rss_exc)
            if api is None:
                api_category = "API_FALLBACK_SKIPPED_NO_CREDENTIALS"
                failed_channels.append((c, rss_category, api_category))
                warnings.append(f"{c['name']} ({c['id']}): RSS {rss_category}; API fallback skipped (OAuth not configured)")
                sources.append({"name": c["name"], "channel_id": c["id"], "source": "none", "status": "failed", "rss_error": rss_category, "api_fallback": api_category})
                continue
            try:
                fallback_videos = api.recent_channel_videos(c, max_results=15)
                videos.extend(fallback_videos)
                warnings.append(f"{c['name']} ({c['id']}): RSS {rss_category}; YouTube API uploads fallback used")
                sources.append({"name": c["name"], "channel_id": c["id"], "source": "youtube_api_uploads", "status": "ok", "rss_error": rss_category, "video_count": len(fallback_videos)})
            except Exception as api_exc:
                api_category = api_error_category(api_exc)
                failed_channels.append((c, rss_category, api_category))
                warnings.append(f"{c['name']} ({c['id']}): RSS {rss_category}; API fallback {api_category}")
                sources.append({"name": c["name"], "channel_id": c["id"], "source": "none", "status": "failed", "rss_error": rss_category, "api_fallback": api_category})
    if failed_channels and len(failed_channels) == len(channels):
        lines = [f"{str(c['name']).replace(chr(10), ' ').replace(chr(13), ' ')} ({c['id']}): RSS {rss}; API fallback {api_error}" for c, rss, api_error in failed_channels]
        raise AllChannelsUnavailable("All channel video sources failed; previous output was preserved.\n" + "\n".join(lines))
    keywords = [k.casefold() for k in config.get("keywords", [config.get("keyword", "MVCI")])]
    matches = [v for v in videos if any(k in v["title"].casefold() for k in keywords)]
    latest = max(matches, key=lambda v: v["published"]) if matches else None
    state = None
    playlist_result = {"status": "credentials_missing", "added": []}
    if api is not None:
        if latest:
            state = api.live_state(latest["video_id"])
        # Playlist writes are attempted before files are replaced. Any failure blocks publishing.
        if matches:
            playlist_result = {"status": "synced", **sync_playlist(
                api, config.get("playlist_id", "PLIA2oKVHJxPs"), matches,
                latest["video_id"] if latest else None, int(config.get("max_playlist_additions_per_run", 10)))}
        else:
            playlist_result = {"status": "no_candidates", "added": []}
    now = datetime.now(timezone.utc)
    payload = {"generated_at": now.isoformat().replace("+00:00", "Z"), "status": "latest_match" if latest else "no_match", "live": state, "live_label": live_label(state), "playlist": playlist_result, "warnings": warnings, "sources": sources,
               "video": ({"title": latest["title"], "video_id": latest["video_id"], "url": latest["url"], "channel": latest["channel"], "published": latest["published"].isoformat().replace("+00:00", "Z")} if latest else None)}
    output_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(output_dir / "index.html", generate_html(latest, warnings, config, state, now, credentials_available(env)).encode("utf-8"))
    write_atomic(output_dir / "feed.xml", rss_feed(latest, config, now, state))
    write_atomic(output_dir / "latest.json", (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return payload


if __name__ == "__main__":
    try:
        result = build()
    except AllChannelsUnavailable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    print(f"{result['status']}: {result['video']['title'] if result['video'] else '該当なし'}")
