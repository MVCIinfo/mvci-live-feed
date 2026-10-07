import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


FIXTURE = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>abcdefghijk</yt:videoId><title>MVCI &amp; friends &lt;test&gt;</title><published>2026-10-06T12:00:00+00:00</published></entry>
<entry><yt:videoId>zyxwvutsrqp</yt:videoId><title>Unrelated video</title><published>2026-10-07T12:00:00+00:00</published></entry>
</feed>'''


class FeedTests(unittest.TestCase):
    def test_parse_and_html_escape(self):
        ch = {"name": "<host>", "id": "UCx"}
        videos = build.parse_feed(FIXTURE, ch)
        self.assertEqual(len(videos), 2)
        page = build.generate_html(videos[0], [], {"title": "MVCI <feed>"})
        self.assertIn("MVCI &amp; friends &lt;test&gt;", page)
        self.assertNotIn("<feed>", page)

    def test_partial_failure_writes_latest_and_valid_rss(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"title": "MVCI", "keywords": ["mvci"], "channels": [
                {"name": "Good", "id": "UC1", "enabled": True}, {"name": "Down", "id": "UC2", "enabled": True}]}), encoding="utf-8")
            def fetch(ch):
                if ch["id"] == "UC2":
                    raise OSError("offline")
                return build.parse_feed(FIXTURE, ch)
            result = build.build(cfg, Path(d) / "site", fetch)
            self.assertEqual(result["status"], "latest_match")
            self.assertEqual(len(result["warnings"]), 1)
            parsed = build.ET.parse(Path(d) / "site" / "feed.xml")
            self.assertEqual(parsed.getroot().tag, "rss")
            self.assertEqual(parsed.findtext("channel/item/title"), "配信状態を確認できません｜MVCI & friends <test>")
            self.assertEqual(parsed.findtext("channel/item/pubDate"), "Tue, 06 Oct 2026 12:00:00 +0000")
            obj = json.loads((Path(d) / "site" / "latest.json").read_text(encoding="utf-8"))
            self.assertIsNone(obj["live"])
            self.assertIn("最新", (Path(d) / "site" / "index.html").read_text(encoding="utf-8"))

    def test_all_failures_preserve_previous_output(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"channels": [{"name": "Bad", "id": "UCx", "enabled": True}]}), encoding="utf-8")
            out = Path(d) / "site"
            out.mkdir()
            (out / "index.html").write_text("previous", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                build.build(cfg, out, lambda ch: (_ for _ in ()).throw(OSError()))
            self.assertEqual((out / "index.html").read_text(encoding="utf-8"), "previous")

    def test_no_match_is_reported_honestly(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"title": "MVCI", "keywords": ["mvci"], "channels": [
                {"name": "Good", "id": "UC1", "enabled": True}]}), encoding="utf-8")
            result = build.build(cfg, Path(d) / "site", lambda ch: [v for v in build.parse_feed(FIXTURE, ch) if v["video_id"] == "zyxwvutsrqp"])
            self.assertEqual(result["status"], "no_match")
            self.assertIsNone(result["video"])
            self.assertIn("見つかりません", (Path(d) / "site" / "index.html").read_text(encoding="utf-8"))

    def test_playlist_sync_failure_blocks_static_publish(self):
        class BrokenPlaylistAPI:
            def __init__(self, env):
                pass
            def live_state(self, video_id):
                return True
            def playlist_video_ids(self, playlist_id):
                raise RuntimeError("simulated quota failure")

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"title": "MVCI", "keywords": ["mvci"], "channels": [
                {"name": "Good", "id": "UC1", "enabled": True}]}), encoding="utf-8")
            out = Path(d) / "site"
            out.mkdir()
            (out / "index.html").write_text("previous page", encoding="utf-8")
            env = {"YOUTUBE_CLIENT_ID": "client", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "refresh"}
            with self.assertRaisesRegex(RuntimeError, "simulated quota failure"):
                build.build(cfg, out, lambda ch: build.parse_feed(FIXTURE, ch), BrokenPlaylistAPI, env)
            self.assertEqual((out / "index.html").read_text(encoding="utf-8"), "previous page")

    def test_newest_match_stays_selected_even_when_api_reports_not_live(self):
        class PlaylistAPI:
            def __init__(self, env):
                self.ids = []
                self.checked = None
            def live_state(self, video_id):
                self.checked = video_id
                return False
            def playlist_video_ids(self, playlist_id):
                rows = {video_id: {"id": "item-" + video_id,
                                   "snippet": {"position": index, "resourceId": {"videoId": video_id}}}
                        for index, video_id in enumerate(self.ids)}
                return list(self.ids), rows
            def add_playlist_video(self, playlist_id, video_id):
                self.ids.insert(0, video_id)
            def move_playlist_item_to_top(self, item, playlist_id):
                video_id = item["snippet"]["resourceId"]["videoId"]
                self.ids.remove(video_id)
                self.ids.insert(0, video_id)

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"title": "MVCI", "keywords": ["mvci"], "channels": [
                {"name": "Good", "id": "UC1", "enabled": True}]}), encoding="utf-8")
            def candidates(channel):
                rows = build.parse_feed(FIXTURE, channel)
                rows[0]["title"] = "MVCI older stream"
                rows[1]["title"] = "MVCI newest stream"
                return rows
            api = PlaylistAPI({})
            env = {"YOUTUBE_CLIENT_ID": "client", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "refresh"}
            result = build.build(cfg, Path(d) / "site", candidates, lambda env: api, env)
            self.assertEqual(result["video"]["video_id"], "zyxwvutsrqp")
            self.assertIs(result["live"], False)
            self.assertEqual(api.checked, "zyxwvutsrqp")


if __name__ == "__main__":
    unittest.main()
