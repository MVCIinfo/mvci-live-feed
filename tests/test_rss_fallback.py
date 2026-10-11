import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build
import youtube_api


ENV = {"YOUTUBE_CLIENT_ID": "client", "YOUTUBE_CLIENT_SECRET": "secret", "YOUTUBE_REFRESH_TOKEN": "refresh"}
RSS_XML = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>aaaaaaaaaaa</yt:videoId><title>MVCI RSS older</title><published>2026-10-10T10:00:00Z</published></entry></feed>'''


def video(video_id, title, published):
    return {"video_id": video_id, "title": title,
            "published": datetime.fromisoformat(published.replace("Z", "+00:00")),
            "channel": "API channel", "channel_id": "UCfallback", "url": "https://www.youtube.com/watch?v=" + video_id}


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.data


class RSSFallbackTests(unittest.TestCase):
    def config(self, path, channels):
        path.write_text(json.dumps({"title": "MVCI", "keywords": ["mvci"], "channels": channels}), encoding="utf-8")

    def test_api_fallback_supplies_newer_match_then_live_and_playlist_sync_use_same_client(self):
        class API:
            def __init__(self, env):
                self.items = []
                self.calls = []
            def recent_channel_videos(self, channel, max_results):
                self.calls.append(("fallback", channel["id"], max_results))
                return [video("bbbbbbbbbbb", "MVCI fallback newest", "2026-10-11T10:00:00Z")]
            def live_state(self, video_id):
                self.calls.append(("live", video_id))
                return True
            def playlist_video_ids(self, playlist):
                return list(self.items), {item: {"id": "item-" + item, "snippet": {"position": n}}
                                           for n, item in enumerate(self.items)}
            def add_playlist_video(self, playlist, video_id):
                self.calls.append(("insert", video_id))
                self.items.insert(0, video_id)
            def move_playlist_item_to_top(self, item, playlist):
                self.calls.append(("move", item["id"]))
        api = API(ENV)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            self.config(cfg, [{"name": "RSS", "id": "UCrss", "enabled": True},
                              {"name": "Fallback channel", "id": "UCfallback", "enabled": True}])
            def fetch(channel):
                if channel["id"] == "UCrss":
                    return build.parse_feed(RSS_XML, channel)
                raise OSError("network down")
            result = build.build(cfg, Path(d) / "site", fetch, lambda env: api, ENV)
            self.assertEqual(result["video"]["video_id"], "bbbbbbbbbbb")
            self.assertIs(result["live"], True)
            self.assertEqual(result["sources"][1]["source"], "youtube_api_uploads")
            self.assertIn(("fallback", "UCfallback", 15), api.calls)
            self.assertIn(("live", "bbbbbbbbbbb"), api.calls)
            self.assertIn(("insert", "bbbbbbbbbbb"), api.calls)
            self.assertEqual(api.items, ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_all_rss_and_api_failures_preserve_previous_output_and_report_sanitely(self):
        class API:
            def __init__(self, env): pass
            def recent_channel_videos(self, channel, max_results):
                raise RuntimeError("SECRET URL token response details")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            self.config(cfg, [{"name": "Channel one", "id": "UCchannelone", "enabled": True}])
            out = Path(d) / "site"
            out.mkdir()
            (out / "index.html").write_text("old page", encoding="utf-8")
            with self.assertRaises(build.AllChannelsUnavailable) as raised:
                build.build(cfg, out, lambda c: (_ for _ in ()).throw(OSError("private")), API, ENV)
            message = str(raised.exception)
            self.assertIn("Channel one (UCchannelone)", message)
            self.assertIn("NETWORK_ERROR", message)
            self.assertIn("API_FALLBACK_ERROR", message)
            self.assertNotIn("SECRET", message)
            self.assertNotIn("private", message)
            self.assertEqual((out / "index.html").read_text(encoding="utf-8"), "old page")

    def test_no_credentials_skips_api_and_all_failures_preserve_output(self):
        class API:
            def __init__(self, env): raise AssertionError("should not be constructed")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            self.config(cfg, [{"name": "RSS only", "id": "UConlyrss", "enabled": True}])
            out = Path(d) / "site"
            out.mkdir()
            (out / "index.html").write_text("old page", encoding="utf-8")
            with self.assertRaises(build.AllChannelsUnavailable) as raised:
                build.build(cfg, out, lambda c: (_ for _ in ()).throw(OSError()), API, {})
            self.assertIn("API_FALLBACK_SKIPPED_NO_CREDENTIALS", str(raised.exception))
            self.assertEqual((out / "index.html").read_text(encoding="utf-8"), "old page")

    def test_partial_coverage_can_still_publish_rss_success(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            cfg = Path(d) / "config.json"
            self.config(cfg, [{"name": "Good", "id": "UCgood", "enabled": True},
                              {"name": "Down", "id": "UCdown", "enabled": True}])
            def fetch(channel):
                if channel["id"] == "UCgood":
                    return build.parse_feed(RSS_XML, channel)
                raise OSError("private network error")
            result = build.build(cfg, Path(d) / "site", fetch, env={})
            self.assertEqual(result["video"]["video_id"], "aaaaaaaaaaa")
            self.assertEqual(result["sources"][0]["status"], "ok")
            self.assertEqual(result["sources"][1]["api_fallback"], "API_FALLBACK_SKIPPED_NO_CREDENTIALS")


class FetchRetryTests(unittest.TestCase):
    channel = {"name": "Retry", "id": "UCretry"}

    def test_malformed_xml_and_unexpected_root_are_parse_errors(self):
        for body in (b"<not-xml", b"<rss><entry/></rss>"):
            with self.subTest(body=body):
                with self.assertRaises(build.ChannelFetchError) as raised:
                    build.fetch_channel(self.channel, lambda *a, **kw: FakeResponse(body), lambda delay: None)
                self.assertEqual(raised.exception.category, "XML_PARSE_ERROR")

    def test_transient_http_retries_with_bounded_delays(self):
        calls, delays = [], []
        def opener(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("https://invalid", 503, "secret", {}, None)
            return FakeResponse(RSS_XML)
        videos = build.fetch_channel(self.channel, opener, delays.append)
        self.assertEqual(len(videos), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(delays, [1])

    def test_nontransient_http_is_not_retried(self):
        calls, delays = [], []
        def opener(*args, **kwargs):
            calls.append(1)
            raise urllib.error.HTTPError("https://invalid", 403, "secret", {}, None)
        with self.assertRaises(build.ChannelFetchError) as raised:
            build.fetch_channel(self.channel, opener, delays.append)
        self.assertEqual(raised.exception.category, "HTTP_403")
        self.assertEqual(len(calls), 1)
        self.assertEqual(delays, [])


class UploadsFallbackAPITests(unittest.TestCase):
    def test_uploads_playlist_is_taken_only_from_channel_resource(self):
        api = youtube_api.YouTubeAPI(env={})
        calls = []
        def fake_call(method, path, params, body=None):
            calls.append((path, params))
            if path == "/channels":
                return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUrealuploads"}}}]}
            return {"items": [{
                "snippet": {"title": "MVCI API video", "publishedAt": "2026-10-10T00:00:00Z"},
                "contentDetails": {"videoId": "ccccccccccc", "videoPublishedAt": "2026-10-09T00:00:00Z"},
            }]}
        api.call = fake_call
        channel = {"id": "UCoriginal", "name": "Original name"}
        videos = api.recent_channel_videos(channel, max_results=15)
        self.assertEqual(calls[0], ("/channels", {"part": "contentDetails", "id": "UCoriginal"}))
        self.assertEqual(calls[1][0], "/playlistItems")
        self.assertEqual(calls[1][1]["playlistId"], "UUrealuploads")
        self.assertEqual(calls[1][1]["maxResults"], 15)
        self.assertEqual(videos[0]["published"].isoformat(), "2026-10-09T00:00:00+00:00")
        self.assertEqual(videos[0]["channel"], "Original name")

    def test_missing_uploads_playlist_does_not_guess_one(self):
        api = youtube_api.YouTubeAPI(env={})
        api.call = lambda *args, **kwargs: {"items": [{"contentDetails": {"relatedPlaylists": {}}}]}
        with self.assertRaisesRegex(RuntimeError, "API_UPLOADS_PLAYLIST_UNAVAILABLE"):
            api.recent_channel_videos({"id": "UCoriginal", "name": "Name"})


if __name__ == "__main__":
    unittest.main()
