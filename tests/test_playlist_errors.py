import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import youtube_api


SECRET_MARKER = "PRIVATE-URL-HEADER-OR-RESPONSE-MARKER"
ALLOWED = (
    "manualSortRequired", "invalidPlaylistItemPosition", "invalidResourceType", "invalidContentDetails",
    "playlistOperationUnsupported", "videoAlreadyInAnotherSeriesPlaylist", "playlistIdRequired",
    "resourceIdRequired", "channelIdRequired", "playlistItemsNotAccessible", "forbidden",
    "insufficientPermissions", "quotaExceeded", "playlistNotFound", "videoNotFound", "accessNotConfigured",
)


def response_error(status, reason, extra=None):
    error = {"errors": [{"reason": reason, "message": SECRET_MARKER, "location": SECRET_MARKER}]}
    payload = {"error": error, "error_description": SECRET_MARKER, "request_url": SECRET_MARKER}
    if extra:
        payload.update(extra)
    return urllib.error.HTTPError(
        "https://example.invalid/" + SECRET_MARKER, status, "reason=" + SECRET_MARKER,
        {"X-Debug": SECRET_MARKER}, io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


class PlaylistApiErrorTests(unittest.TestCase):
    def call_api(self, error):
        api = youtube_api.YouTubeAPI(env={})
        api.opener = lambda *args, **kwargs: (_ for _ in ()).throw(error)
        request = youtube_api.urllib.request.Request("https://example.invalid/path?token=" + SECRET_MARKER)
        with self.assertRaises(RuntimeError) as raised:
            api._json_request(request)
        return raised.exception

    def test_allowlisted_reasons_include_status_but_no_untrusted_text(self):
        for reason in ALLOWED:
            with self.subTest(reason=reason):
                message = str(self.call_api(response_error(400, reason)))
                self.assertIn("HTTP 400", message)
                self.assertIn(reason, message)
                self.assertNotIn(SECRET_MARKER, message)
        manual = str(self.call_api(response_error(400, "manualSortRequired")))
        self.assertIn("手動", manual)
        self.assertIn("設定", manual)

    def test_unknown_or_malformed_reason_is_not_exposed(self):
        unknown = str(self.call_api(response_error(403, SECRET_MARKER)))
        self.assertIn("HTTP 403", unknown)
        self.assertNotIn(SECRET_MARKER, unknown)
        malformed_reason = response_error(400, [SECRET_MARKER])
        malformed = str(self.call_api(malformed_reason))
        self.assertIn("HTTP 400", malformed)
        self.assertNotIn(SECRET_MARKER, malformed)

    def test_error_cause_does_not_carry_original_http_error(self):
        api = youtube_api.YouTubeAPI(env={})
        api.opener = lambda *args, **kwargs: (_ for _ in ()).throw(response_error(400, "manualSortRequired"))
        request = youtube_api.urllib.request.Request("https://example.invalid/" + SECRET_MARKER)
        try:
            api._json_request(request)
        except RuntimeError as exc:
            self.assertIsNone(exc.__cause__)
            self.assertIsNone(exc.__context__)
        else:
            self.fail("expected sanitized API error")


if __name__ == "__main__":
    unittest.main()
