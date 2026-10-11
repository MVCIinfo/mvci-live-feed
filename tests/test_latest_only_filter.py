import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build


class FakePlaylistAPI:
    def __init__(self, env):
        self.items = []
        self.added = []
        self.moved = []
        self.list_calls = 0
    def live_state(self, video_id):
        return False
    def playlist_video_ids(self, playlist_id):
        self.list_calls += 1
        rows = {video_id: {"id": "item-" + video_id,
                           "snippet": {"position": index, "resourceId": {"videoId": video_id}}}
                for index, video_id in enumerate(self.items)}
        return list(self.items), rows
    def add_playlist_video(self, playlist_id, video_id):
        self.added.append(video_id)
        self.items.insert(0, video_id)
    def move_playlist_item_to_top(self, item, playlist_id):
        video_id = item["snippet"]["resourceId"]["videoId"]
        self.moved.append(video_id)
        self.items.remove(video_id)
        self.items.insert(0, video_id)


def make_video(video_id, title, day):
    return {"video_id": video_id, "title": title,
            "published": datetime(2026, 10, day, tzinfo=timezone.utc),
            "channel": "Test", "channel_id": "UCtest",
            "url": "https://www.youtube.com/watch?v=" + video_id}


class LatestOnlyFilterTests(unittest.TestCase):
    def run_build(self, titles, *, exclude_field=None):
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temp.cleanup)
        directory = Path(temp.name)
        config_path = directory / "config.json"
        config = {"title": "MVCI", "keywords": ["MVCI"], "channels": [
            {"name": "Test", "id": "UCtest", "enabled": True}]}
        if exclude_field is not None:
            config["exclude_keywords"] = exclude_field
        config_path.write_text(json.dumps(config), encoding="utf-8")
        videos = [make_video(f"{index:011d}", title, 10 + index) for index, title in enumerate(titles)]
        api = FakePlaylistAPI({"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "token"})
        result = build.build(config_path, directory / "site", lambda channel: videos,
                             lambda env: api, {"YOUTUBE_CLIENT_ID": "id", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "token"})
        return result, api

    def test_newest_excluded_uses_next_eligible_and_only_syncs_that_video(self):
        titles = ["MVCI regular earlier", "MVCI regular newest", "MVCI 闘魂部 newest overall"]
        result, api = self.run_build(titles)
        eligible_id = f"{1:011d}"
        self.assertEqual(result["video"]["video_id"], eligible_id)
        self.assertEqual(api.added, [eligible_id])
        self.assertEqual(api.items, [eligible_id])

    def test_all_excluded_titles_mean_no_candidate_and_no_playlist_write(self):
        titles = ["MVCI闘魂部配信", "MVCI　闘魂部大会", "MVCI\n闘魂部"]
        result, api = self.run_build(titles)
        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["video"])
        self.assertEqual(api.added, [])
        self.assertEqual(api.list_calls, 0)

    def test_exclusion_ignores_case_and_whitespace_but_not_unrelated_phrase(self):
        exclusions = ["MVCI 闘魂部"]
        for title in ("MVCI闘魂部", "mVcI 闘魂部", "MVCI　闘魂部", "MVCI\n闘魂部"):
            with self.subTest(title=title):
                self.assertTrue(build.is_excluded_title(title, exclusions))
        self.assertFalse(build.is_excluded_title("MVCI 決勝 闘魂部", exclusions))
        self.assertFalse(build.is_excluded_title("闘魂部", exclusions))

    def test_configured_exclusion_keywords_are_respected(self):
        result, api = self.run_build(["MVCI regular older", "MVCI special series newest"], exclude_field=["MVCI special"])
        self.assertEqual(result["video"]["video_id"], f"{0:011d}")
        self.assertEqual(api.added, [f"{0:011d}"])


if __name__ == "__main__":
    unittest.main()
