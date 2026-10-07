import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import youtube_api
import build
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import authorize_youtube


class LiveStateTests(unittest.TestCase):
    def state(self, item):
        api = youtube_api.YouTubeAPI(env={})
        api.call = lambda *args, **kwargs: {"items": [] if item is None else [item]}
        return api.live_state("abcdefghijk")

    def test_live_requires_live_broadcast_and_no_actual_end(self):
        self.assertIs(self.state({"snippet": {"liveBroadcastContent": "live"}, "liveStreamingDetails": {}}), True)
        self.assertIs(self.state({"snippet": {"liveBroadcastContent": "live"}, "liveStreamingDetails": {"actualEndTime": "2026-10-08T00:00:00Z"}}), False)

    def test_offline_upcoming_and_unknown_states(self):
        self.assertIs(self.state({"snippet": {"liveBroadcastContent": "none"}}), False)
        self.assertIs(self.state({"snippet": {"liveBroadcastContent": "upcoming"}}), False)
        self.assertIsNone(self.state(None))
        self.assertIsNone(self.state({"snippet": {}}))

    def test_api_error_is_unknown(self):
        api = youtube_api.YouTubeAPI(env={})
        api.call = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private"))
        self.assertIsNone(api.live_state("abcdefghijk"))

    def test_rss_uses_exact_live_offline_and_unknown_prefixes(self):
        video = {"video_id": "abcdefghijk", "title": "MVCI event", "url": "https://www.youtube.com/watch?v=abcdefghijk",
                 "channel": "Channel", "published": datetime(2026, 10, 8, tzinfo=timezone.utc)}
        expected = {True: "配信中！｜MVCI event", False: "直近のMVCI配信｜MVCI event", None: "配信状態を確認できません｜MVCI event"}
        for state, label in expected.items():
            with self.subTest(state=state):
                xml = build.rss_feed(video, {"title": "MVCI"}, datetime(2026, 10, 8, tzinfo=timezone.utc), state)
                root = build.ET.fromstring(xml)
                self.assertEqual(root.findtext("channel/item/title"), label)


class PlaylistSyncTests(unittest.TestCase):
    def video(self, video_id, day):
        return {"video_id": video_id, "published": datetime(2026, 10, day, tzinfo=timezone.utc)}

    class FakeAPI:
        def __init__(self, pages):
            self.pages = list(pages)
            self.added = []
            self.moved = []
            self.list_count = 0

        def playlist_video_ids(self, playlist):
            self.list_count += 1
            if self.list_count == 1:
                rows = {key: value for page in self.pages for key, value in page.items()}
                ids = list(rows)
                return ids, rows
            # Reflect insert-at-top and move operation in a subsequent listing.
            rows = {}
            ordered = self.added + [key for page in self.pages for key in page if key not in self.added]
            if self.moved:
                ordered = [self.moved[-1]] + [v for v in ordered if v != self.moved[-1]]
            for position, vid in enumerate(ordered):
                rows[vid] = {"id": "item-" + vid, "snippet": {"position": position, "resourceId": {"videoId": vid}}}
            return ordered, rows

        def add_playlist_video(self, playlist, video_id):
            self.added.insert(0, video_id)

        def move_playlist_item_to_top(self, item, playlist):
            self.moved.append(item["snippet"]["resourceId"]["videoId"])

    def test_paginates_deduplicates_and_moves_existing_selected_to_top(self):
        rows1 = {"old00000001": {"id": "item-old", "snippet": {"position": 0}}}
        rows2 = {"sel00000001": {"id": "item-sel", "snippet": {"position": 2}}}
        api = self.FakeAPI([rows1, rows2])
        videos = [self.video("old00000001", 1), self.video("new00000001", 2), self.video("sel00000001", 3)]
        result = youtube_api.sync_playlist(api, "PLx", videos, "sel00000001", 10)
        self.assertEqual(api.added, ["new00000001"])
        self.assertEqual(api.moved, ["sel00000001"])
        self.assertEqual(result["added"], ["new00000001"])
        self.assertTrue(result["moved_selected"])

    def test_selected_new_video_has_priority_under_limit_and_is_top(self):
        api = self.FakeAPI([{}])
        videos = [self.video("old00000001", 1), self.video("sel00000001", 3), self.video("mid00000001", 2)]
        result = youtube_api.sync_playlist(api, "PLx", videos, "sel00000001", 2)
        self.assertEqual(result["added"], ["old00000001", "sel00000001"])
        self.assertEqual(api.moved, [])

    def test_api_reads_all_playlist_pages(self):
        api = youtube_api.YouTubeAPI(env={})
        seen = []
        def fake_call(method, path, params, body=None):
            seen.append(params)
            if len(seen) == 1:
                return {"items": [{"contentDetails": {"videoId": "first000001"}}], "nextPageToken": "next"}
            return {"items": [{"contentDetails": {"videoId": "second00001"}}]}
        api.call = fake_call
        ids, rows = api.playlist_video_ids("PLx")
        self.assertEqual(ids, ["first000001", "second00001"])
        self.assertEqual(seen[1]["pageToken"], "next")


class OAuthCallbackTests(unittest.TestCase):
    def test_callback_requires_matching_state_and_returns_code_without_logging(self):
        code, error = authorize_youtube.parse_callback("code=private-code&state=expected", "expected")
        self.assertEqual(code, "private-code")
        self.assertIsNone(error)
        with self.assertRaises(ValueError):
            authorize_youtube.parse_callback("code=private-code&state=wrong", "expected")


if __name__ == "__main__":
    unittest.main()
