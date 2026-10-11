import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import youtube_api


SELECTED = "sel00000001"


class ListingAPI:
    def __init__(self, listings):
        self.listings = list(listings)
        self.added = []
        self.moved = []
        self.reads = 0

    def playlist_video_ids(self, playlist_id):
        self.reads += 1
        index = min(self.reads - 1, len(self.listings) - 1)
        rows = self.listings[index]
        return list(rows), rows

    def add_playlist_video(self, playlist_id, video_id):
        self.added.append(video_id)

    def move_playlist_item_to_top(self, row, playlist_id):
        self.moved.append(row["snippet"]["resourceId"]["videoId"])


def row(video_id, position):
    return {video_id: {"id": "item-" + video_id, "snippet": {
        "position": position, "resourceId": {"videoId": video_id},
    }}}


def candidate():
    return [{"video_id": SELECTED, "published": "2026-10-11T00:00:00Z"}]


class PlaylistSyncVerificationTests(unittest.TestCase):
    def test_delayed_visibility_retries_read_without_duplicate_insert(self):
        api = ListingAPI([{}, {}, row(SELECTED, 0)])
        delays = []
        result = youtube_api.sync_playlist(api, "PL-public", candidate(), SELECTED, 1, delays.append)
        self.assertEqual(result["added"], [SELECTED])
        self.assertEqual(api.added, [SELECTED])
        self.assertEqual(api.moved, [])
        self.assertEqual(delays, [1])

    def test_persistent_missing_item_blocks_sync_with_safe_diagnostics(self):
        api = ListingAPI([{}, {}])
        delays = []
        with self.assertRaisesRegex(RuntimeError, "playlist=PL-public.*video=sel00000001.*added_this_run=True.*cap=1"):
            youtube_api.sync_playlist(api, "PL-public", candidate(), SELECTED, 1, delays.append)
        self.assertEqual(api.added, [SELECTED])
        self.assertEqual(delays, [1, 3])

    def test_delayed_move_verification_retries_without_repeating_move(self):
        api = ListingAPI([row(SELECTED, 2), row(SELECTED, 2), row(SELECTED, 2), row(SELECTED, 0)])
        delays = []
        result = youtube_api.sync_playlist(api, "PL-public", candidate(), SELECTED, 0, delays.append)
        self.assertEqual(api.added, [])
        self.assertEqual(api.moved, [SELECTED])
        self.assertTrue(result["moved_selected"])
        self.assertEqual(delays, [1])

    def test_zero_cap_missing_selected_fails_before_any_write(self):
        api = ListingAPI([{}])
        with self.assertRaisesRegex(RuntimeError, "追加上限が0以下.*max_playlist_additions_per_run.*1以上"):
            youtube_api.sync_playlist(api, "PL-public", candidate(), SELECTED, 0, lambda _: self.fail("unexpected retry"))
        self.assertEqual(api.added, [])
        self.assertEqual(api.moved, [])
        self.assertEqual(api.reads, 1)

    def test_zero_cap_is_allowed_when_selected_item_already_exists(self):
        api = ListingAPI([row(SELECTED, 0), row(SELECTED, 0)])
        result = youtube_api.sync_playlist(api, "PL-public", candidate(), SELECTED, 0, lambda _: self.fail("unexpected retry"))
        self.assertEqual(result["added"], [])
        self.assertEqual(api.added, [])


if __name__ == "__main__":
    unittest.main()
