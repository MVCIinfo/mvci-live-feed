import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


ENV = {"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "token"}


class FakeAPI:
    def __init__(self, items=(), live=False):
        self.items = list(items)
        self.added = []
        self.moved = []
        self.live = live

    def live_state(self, video_id):
        return self.live

    def playlist_video_ids(self, playlist_id):
        rows = {vid: {"id": "item-" + vid, "snippet": {"position": n, "resourceId": {"videoId": vid}}}
                for n, vid in enumerate(self.items)}
        return list(self.items), rows

    def add_playlist_video(self, playlist_id, video_id):
        self.added.append(video_id)
        self.items.insert(0, video_id)

    def move_playlist_item_to_top(self, row, playlist_id):
        vid = row["snippet"]["resourceId"]["videoId"]
        self.moved.append(vid)
        self.items.remove(vid)
        self.items.insert(0, vid)


def video(video_id, title, channel_id, channel, day):
    return {"video_id": video_id, "title": title,
            "published": datetime(2026, 10, day, tzinfo=timezone.utc),
            "channel": channel, "channel_id": channel_id,
            "url": "https://www.youtube.com/watch?v=" + video_id}


class PerChannelPlaylistTests(unittest.TestCase):
    def run_feed(self, videos_by_channel, api, *, keyword="MVCI"):
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = {"title": "MVCI", "keywords": [keyword], "playlist_id": "PL-public",
                  "max_playlist_additions_per_run": 10,
                  "channels": [{"name": "Alpha", "id": "UCalpha", "enabled": True},
                               {"name": "Beta", "id": "UCbeta", "enabled": True}]}
        cfg = root / "config.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        result = build.build(cfg, root / "site",
                             lambda channel: videos_by_channel[channel["id"]],
                             lambda env: api, ENV)
        return result, root / "site"

    def test_playlist_gets_latest_eligible_per_channel_but_page_and_rss_get_overall_latest(self):
        a_latest = video("a0000000001", "MVCI Alpha latest", "UCalpha", "Alpha", 14)
        b_latest = video("b0000000001", "MVCI Beta latest", "UCbeta", "Beta", 13)
        videos = {
            "UCalpha": [video("a0000000002", "MVCI Alpha old", "UCalpha", "Alpha", 9), a_latest,
                        video("a0000000003", "MVCI 闘魂部 Alpha excluded", "UCalpha", "Alpha", 16)],
            "UCbeta": [video("b0000000002", "MVCI Beta old", "UCbeta", "Beta", 8), b_latest,
                       video("b0000000003", "MVCI 闘魂部 Beta excluded", "UCbeta", "Beta", 17)],
        }
        api = FakeAPI(items=[a_latest["video_id"]])
        result, site = self.run_feed(videos, api)
        self.assertEqual(result["video"]["video_id"], a_latest["video_id"])
        self.assertEqual(api.added, [b_latest["video_id"]])
        self.assertEqual(api.items[0], a_latest["video_id"])
        self.assertEqual(api.moved, [a_latest["video_id"]])
        self.assertEqual(result["playlist"]["added"], [b_latest["video_id"]])
        self.assertEqual(len(ET.parse(site / "feed.xml").findall("channel/item")), 1)
        payload = json.loads((site / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["video"]["video_id"], a_latest["video_id"])
        page = (site / "index.html").read_text(encoding="utf-8")
        self.assertIn(a_latest["video_id"], page)
        self.assertNotIn(b_latest["video_id"], page)

    def test_badge_is_live_only_for_latest_video_confirmed_live(self):
        latest = video("a0000000001", "MVCI Alpha latest", "UCalpha", "Alpha", 14)
        videos = {"UCalpha": [latest], "UCbeta": []}
        live_api = FakeAPI(live=True)
        _, live_site = self.run_feed(videos, live_api)
        self.assertEqual((live_site / "live-status.png").read_bytes(), build.BADGE_LIVE.read_bytes())

        offline_api = FakeAPI(live=False)
        _, offline_site = self.run_feed(videos, offline_api)
        self.assertEqual((offline_site / "live-status.png").read_bytes(), build.BADGE_BLANK.read_bytes())

        no_match_api = FakeAPI(live=True)
        no_match, no_match_site = self.run_feed(videos, no_match_api, keyword="not found")
        self.assertIsNone(no_match["video"])
        self.assertEqual((no_match_site / "live-status.png").read_bytes(), build.BADGE_BLANK.read_bytes())


if __name__ == "__main__":
    unittest.main()
