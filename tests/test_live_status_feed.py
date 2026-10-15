import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


VIDEO = {
    "video_id": "abcdefghijk",
    "title": "MVCI & <Special> stream",
    "url": "https://www.youtube.com/watch?v=abcdefghijk",
    "channel": "Channel & Friends",
    "channel_id": "UCfixture",
    "published": datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc),
}
CONFIG = {"title": "MVCI feed", "site_url": "https://example.test/feed/"}
GENERATED = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)


class LiveStatusFeedTests(unittest.TestCase):
    def test_live_true_emits_one_valid_escaped_rss_item_for_selected_video(self):
        data = build.live_status_feed(VIDEO, CONFIG, GENERATED, True)
        root = ET.fromstring(data)
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.attrib["version"], "2.0")
        self.assertEqual(root.findtext("channel/title"), "MVCI feed 配信中のみ")
        self.assertEqual(root.findtext("channel/link"), CONFIG["site_url"])
        self.assertTrue(root.findtext("channel/lastBuildDate"))
        items = root.findall("channel/item")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].findtext("title"), "🔴 配信中！")
        self.assertEqual(items[0].findtext("link"), VIDEO["url"])
        self.assertEqual(items[0].findtext("guid"), VIDEO["url"])
        self.assertIn("MVCI & <Special> stream", items[0].findtext("description"))

    def test_false_unknown_or_missing_video_produces_no_item(self):
        cases = [(VIDEO, False), (VIDEO, None), (None, True), (None, False), (None, None)]
        for video, state in cases:
            with self.subTest(video=video is not None, state=state):
                root = ET.fromstring(build.live_status_feed(video, CONFIG, GENERATED, state))
                self.assertEqual(root.findall("channel/item"), [])

    def test_build_writes_empty_live_status_feed_when_latest_is_offline(self):
        class API:
            def __init__(self, env):
                self.items = []

            def live_state(self, video_id):
                self.asserted_video = video_id
                return False

            def playlist_video_ids(self, playlist_id):
                rows = {video_id: {"id": "item-" + video_id,
                                   "snippet": {"position": index, "resourceId": {"videoId": video_id}}}
                        for index, video_id in enumerate(self.items)}
                return list(self.items), rows

            def add_playlist_video(self, playlist_id, video_id):
                self.items.insert(0, video_id)

            def move_playlist_item_to_top(self, item, playlist_id):
                video_id = item["snippet"]["resourceId"]["videoId"]
                self.items.remove(video_id)
                self.items.insert(0, video_id)

        env = {"YOUTUBE_CLIENT_ID": "fixture-client", "YOUTUBE_CLIENT_SECRET": "fixture-secret",
               "YOUTUBE_REFRESH_TOKEN": "fixture-refresh"}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            root = Path(temp)
            live_badge, blank_badge = build.BADGE_LIVE, build.BADGE_BLANK
            build.BADGE_LIVE, build.BADGE_BLANK = root / "live.png", root / "blank.png"
            build.BADGE_LIVE.write_bytes(b"fixture-live-png")
            build.BADGE_BLANK.write_bytes(b"fixture-transparent-png")
            config_path = root / "config.json"
            config = {**CONFIG, "keywords": ["MVCI"], "channels": [
                {"name": "Fixture", "id": "UCfixture", "enabled": True}],
                "max_playlist_additions_per_run": 1}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            api = API(env)
            try:
                result = build.build(config_path, root / "site", lambda channel: [VIDEO], lambda **kwargs: api, env)
            finally:
                build.BADGE_LIVE, build.BADGE_BLANK = live_badge, blank_badge

            site = root / "site"
            self.assertTrue((site / "live-status.xml").is_file())
            status_root = ET.parse(site / "live-status.xml").getroot()
            self.assertEqual(status_root.findall("channel/item"), [])
            self.assertEqual(result["video"]["video_id"], VIDEO["video_id"])
            self.assertIs(result["live"], False)
            normal_feed = ET.parse(site / "feed.xml").getroot()
            self.assertEqual(len(normal_feed.findall("channel/item")), 1)


if __name__ == "__main__":
    unittest.main()
