#!/usr/bin/env python3
"""Build a static latest-video page from public YouTube channel RSS feeds."""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site"
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
NS = {"a": ATOM, "yt": YT}


def parse_feed(data: bytes, channel: dict) -> list[dict]:
    root = ET.fromstring(data)
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


def fetch_channel(channel: dict, opener=urllib.request.urlopen) -> list[dict]:
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + channel["id"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MVCILiveFeed/1.0)"})
    last_error = None
    for attempt in range(3):
        try:
            with opener(req, timeout=20) as response:
                return parse_feed(response.read(), channel)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
    raise last_error


def generate_html(video: dict | None, warnings: list[str], config: dict) -> str:
    title = html.escape(config.get("title", "MVCI 最新動画"))
    enabled = "、".join(html.escape(c["name"]) for c in config.get("channels", []) if c.get("enabled") and c.get("id"))
    notice = "RSSを確認しました。MVCI関連タイトルの最新動画を表示しています。" if video else "現在、MVCI関連タイトルの動画は見つかりませんでした。"
    if warnings:
        notice += " 一部チャンネルの取得に失敗しています。"
    if video:
        title_text = html.escape(video["title"])
        jst = timezone(timedelta(hours=9))
        detail = html.escape(video["channel"]) + " ・ 公開日時 " + html.escape(video["published"].astimezone(jst).strftime("%Y-%m-%d %H:%M JST"))
        content = f'<div class="player"><iframe src="https://www.youtube-nocookie.com/embed/{html.escape(video["video_id"], quote=True)}" title="{title_text}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen loading="lazy"></iframe></div><h2>{title_text}</h2><p>{detail}</p><p><a href="{html.escape(video["url"], quote=True)}">YouTubeで開く</a></p>'
    else:
        content = '<p class="empty">該当動画が見つかったら、ここに表示されます。</p>'
    warn_html = "" if not warnings else "<details><summary>取得状況</summary><ul>" + "".join("<li>" + html.escape(w) + "</li>" for w in warnings) + "</ul></details>"
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="YouTubeのチャンネルRSSからMVCI関連の最新動画を表示します"><title>{title}</title><style>
:root{{color-scheme:dark;--bg:#10131b;--panel:#1a2030;--text:#f5f7fb;--muted:#aeb8cc;--accent:#70d7bd}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at top,#26324a,var(--bg) 60%);color:var(--text);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{width:min(920px,100%);margin:auto;padding:clamp(20px,5vw,52px)}}header{{margin-bottom:26px}}h1{{font-size:clamp(1.7rem,5vw,2.6rem);margin:0 0 8px}}p{{color:var(--muted)}}.card{{background:var(--panel);border:1px solid #344057;border-radius:18px;padding:clamp(16px,4vw,30px);box-shadow:0 18px 55px #0005}}.player{{position:relative;aspect-ratio:16/9;background:#080a10;border-radius:12px;overflow:hidden}}iframe{{position:absolute;width:100%;height:100%;border:0}}h2{{font-size:clamp(1.15rem,4vw,1.7rem);line-height:1.4;margin:22px 0 0}}a{{color:var(--accent)}}.status{{border-left:3px solid var(--accent);padding:2px 14px;margin:0 0 20px}}.empty{{padding:40px 10px;text-align:center}}small,footer{{color:var(--muted)}}details{{margin-top:18px;color:var(--muted)}}footer{{margin-top:24px;font-size:.9rem}}</style></head><body><main><header><h1>{title}</h1><p>登録チャンネルの動画からMVCI関連タイトルの最新の1本を表示します。対象: {enabled or "未設定"}</p></header><section class="card"><p class="status">{html.escape(notice)}</p>{content}{warn_html}</section><footer><p>このページは最新動画を示すもので、ライブ配信中であることを示すものではありません。日時はYouTube RSSの公開日時です。定期更新は通常1時間ごとで、即時反映を保証しません。</p><p><a href="feed.xml">RSSフィード</a> ・ <a href="latest.json">JSON</a></p></footer></main></body></html>'''


def rss_feed(video: dict | None, config: dict, generated: datetime) -> bytes:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = config.get("title", "MVCI 最新動画")
    ET.SubElement(channel, "link").text = config.get("site_url", "https://MVCIinfo.github.io/mvci-live-feed/")
    ET.SubElement(channel, "description").text = "登録チャンネルからMVCI関連の最新動画を表示するフィードです。"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    if video:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = video["title"]
        ET.SubElement(item, "link").text = video["url"]
        ET.SubElement(item, "guid", isPermaLink="true").text = video["url"]
        ET.SubElement(item, "pubDate").text = format_datetime(video["published"])
        ET.SubElement(item, "description").text = f"{video['channel']} — YouTube RSSの公開日時です。ライブ開始時刻ではありません。"
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


def build(config_path: Path = ROOT / "config.json", output_dir: Path = OUT, fetcher=fetch_channel) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    channels = [c for c in config.get("channels", []) if c.get("enabled") and c.get("id")]
    videos, warnings = [], []
    if not channels:
        raise RuntimeError("有効なチャンネルIDがありません。config.jsonを確認してください。")
    for c in channels:
        try:
            videos.extend(fetcher(c))
        except Exception as exc:  # partial failures are expected for public feeds
            warnings.append(f"{c['name']}: {type(exc).__name__}")
    if not videos and len(warnings) == len(channels):
        raise RuntimeError("すべてのチャンネル取得に失敗したため、既存の出力を保持します。")
    keywords = [k.casefold() for k in config.get("keywords", [config.get("keyword", "MVCI")])]
    matches = [v for v in videos if any(k in v["title"].casefold() for k in keywords)]
    latest = max(matches, key=lambda v: v["published"]) if matches else None
    now = datetime.now(timezone.utc)
    payload = {"generated_at": now.isoformat().replace("+00:00", "Z"), "status": "latest_match" if latest else "no_match", "live": None, "warnings": warnings,
               "video": ({"title": latest["title"], "video_id": latest["video_id"], "url": latest["url"], "channel": latest["channel"], "published": latest["published"].isoformat().replace("+00:00", "Z")} if latest else None)}
    output_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(output_dir / "index.html", generate_html(latest, warnings, config).encode("utf-8"))
    write_atomic(output_dir / "feed.xml", rss_feed(latest, config, now))
    write_atomic(output_dir / "latest.json", (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return payload


if __name__ == "__main__":
    result = build()
    print(f"{result['status']}: {result['video']['title'] if result['video'] else '該当なし'}")
