import io
import json
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import youtube_api


SENTINEL = "NEVER-EXPOSE-THIS-RESPONSE-DETAIL"
ENV = {
    "YOUTUBE_CLIENT_ID": "client-id.apps.googleusercontent.com",
    "YOUTUBE_CLIENT_SECRET": "client-secret",
    "YOUTUBE_REFRESH_TOKEN": "refresh-token",
}


def http_error(code, payload):
    return urllib.error.HTTPError(
        youtube_api.TOKEN_URL, code, "bad response", {},
        io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


class OAuthDiagnosticTests(unittest.TestCase):
    def test_known_oauth_errors_are_translated_without_echoing_response(self):
        expected_codes = ("invalid_grant", "invalid_client", "unauthorized_client", "access_denied", "invalid_request")
        for error in expected_codes:
            with self.subTest(error=error):
                api = youtube_api.YouTubeAPI(ENV, opener=lambda *a, **kw: (_ for _ in ()).throw(
                    http_error(400, {"error": error, "error_description": SENTINEL})))
                with self.assertRaises(RuntimeError) as raised:
                    api.access_token()
                self.assertIn(error, str(raised.exception))
                self.assertNotIn(SENTINEL, str(raised.exception))
                self.assertNotIn("client-secret", str(raised.exception))
                self.assertNotIn("refresh-token", str(raised.exception))
                self.assertNotIn(youtube_api.TOKEN_URL, str(raised.exception))

    def test_unknown_error_code_and_body_are_never_exposed(self):
        api = youtube_api.YouTubeAPI(ENV, opener=lambda *a, **kw: (_ for _ in ()).throw(
            http_error(401, {"error": SENTINEL, "error_description": SENTINEL})))
        with self.assertRaises(RuntimeError) as raised:
            api.access_token()
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(SENTINEL, str(raised.exception))

    def test_successful_response_without_token_uses_safe_diagnostic(self):
        api = youtube_api.YouTubeAPI(ENV, opener=lambda *a, **kw: Response(json.dumps(
            {"error": "invalid_grant", "error_description": SENTINEL}).encode()))
        with self.assertRaises(RuntimeError) as raised:
            api.access_token()
        self.assertIn("invalid_grant", str(raised.exception))
        self.assertNotIn(SENTINEL, str(raised.exception))

    def test_whitespace_is_trimmed_before_posting_oauth_values(self):
        captured = []
        def opener(request, timeout):
            captured.append(request)
            return Response(b'{"access_token":"temporary-access-token"}')
        env = {key: "  " + value + " \n" for key, value in ENV.items()}
        self.assertTrue(youtube_api.credentials_available(env))
        self.assertTrue(youtube_api.credentials_present(env))
        api = youtube_api.YouTubeAPI(env, opener=opener)
        self.assertEqual(api.access_token(), "temporary-access-token")
        posted = urllib.parse.parse_qs(captured[0].data.decode("utf-8"))
        self.assertEqual(posted["client_id"][0], ENV["YOUTUBE_CLIENT_ID"])
        self.assertEqual(posted["client_secret"][0], ENV["YOUTUBE_CLIENT_SECRET"])
        self.assertEqual(posted["refresh_token"][0], ENV["YOUTUBE_REFRESH_TOKEN"])

    def test_whitespace_only_secrets_are_not_configured(self):
        env = {key: " \n\t" for key in ENV}
        self.assertFalse(youtube_api.credentials_available(env))
        self.assertFalse(youtube_api.credentials_present(env))

    def test_network_error_does_not_echo_reason(self):
        api = youtube_api.YouTubeAPI(ENV, opener=lambda *a, **kw: (_ for _ in ()).throw(
            urllib.error.URLError(SENTINEL)))
        with self.assertRaises(RuntimeError) as raised:
            api.access_token()
        self.assertIn("URLError", str(raised.exception))
        self.assertNotIn(SENTINEL, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
