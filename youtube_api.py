"""Minimal YouTube Data API v3 client using OAuth refresh credentials."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
SCOPES = ("https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl")


def credentials_available(env=os.environ) -> bool:
    return all(env.get(key) for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))


def credentials_present(env=os.environ) -> bool:
    return any(env.get(key) for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))


class YouTubeAPI:
    def __init__(self, env=os.environ, opener=urllib.request.urlopen):
        self.env = env
        self.opener = opener
        self._token = None

    def _json_request(self, request):
        try:
            with self.opener(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Never include response bodies, URLs, or request headers in logs/errors.
            raise RuntimeError(f"YouTube API returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"YouTube API request failed ({type(exc).__name__})") from None

    def access_token(self) -> str:
        if self._token:
            return self._token
        if not credentials_available(self.env):
            raise RuntimeError("YouTube OAuth credentials are not configured")
        body = urllib.parse.urlencode({
            "client_id": self.env["YOUTUBE_CLIENT_ID"],
            "client_secret": self.env["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": self.env["YOUTUBE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }).encode("ascii")
        request = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            data = self._json_request(request)
        except RuntimeError:
            raise RuntimeError("OAuth token refresh failed") from None
        token = data.get("access_token")
        if not token:
            raise RuntimeError("OAuth token refresh failed")
        self._token = token
        return token

    def call(self, method: str, path: str, params=None, body=None):
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = API_BASE + path + ("?" + query if query else "")
        headers = {"Authorization": "Bearer " + self.access_token(), "Accept": "application/json"}
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=raw, headers=headers, method=method)
        return self._json_request(request)

    def live_state(self, video_id: str) -> bool | None:
        """True=live, False=not live, None=unknown or unavailable."""
        try:
            data = self.call("GET", "/videos", {"part": "snippet,liveStreamingDetails,status", "id": video_id})
            items = data.get("items") or []
            if not items:
                return None
            item = items[0]
            snippet = item.get("snippet") or {}
            details = item.get("liveStreamingDetails") or {}
            state = snippet.get("liveBroadcastContent")
            if state == "live":
                return not bool(details.get("actualEndTime"))
            if state in ("none", "upcoming"):
                return False
            return None
        except RuntimeError:
            return None

    def playlist_video_ids(self, playlist_id: str) -> tuple[list[str], dict[str, dict]]:
        ids, rows, token = [], {}, None
        while True:
            params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if token:
                params["pageToken"] = token
            page = self.call("GET", "/playlistItems", params)
            for item in page.get("items", []):
                video_id = (item.get("contentDetails") or {}).get("videoId")
                if video_id:
                    ids.append(video_id)
                    rows[video_id] = item
            token = page.get("nextPageToken")
            if not token:
                return ids, rows

    def add_playlist_video(self, playlist_id: str, video_id: str) -> None:
        self.call("POST", "/playlistItems", {"part": "snippet"}, {"snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
            "position": 0,
        }})

    def move_playlist_item_to_top(self, item: dict, playlist_id: str) -> None:
        snippet = item.get("snippet") or {}
        resource_id = snippet.get("resourceId") or {}
        body = {"id": item["id"], "snippet": {
            "playlistId": playlist_id,
            "resourceId": resource_id,
            "position": 0,
        }}
        self.call("PUT", "/playlistItems", {"part": "snippet"}, body)


def sync_playlist(api: YouTubeAPI, playlist_id: str, videos: list[dict], selected_id: str | None, max_additions: int = 10) -> dict:
    """Add current matching candidates without deleting or duplicating playlist entries."""
    existing_ids, _ = api.playlist_video_ids(playlist_id)
    existing = set(existing_ids)
    by_id = {v["video_id"]: v for v in videos}
    candidates = [video_id for video_id in by_id if video_id not in existing]
    # Guarantee the selected latest entry fits the quota, then add other matches oldest first.
    ordered = []
    if selected_id in candidates:
        ordered.append(selected_id)
    ordered.extend(sorted((video_id for video_id in candidates if video_id != selected_id),
                          key=lambda video_id: by_id[video_id]["published"]))
    additions = ordered[:max(0, max_additions)]
    additions.sort(key=lambda video_id: by_id[video_id]["published"])
    for video_id in additions:
        api.add_playlist_video(playlist_id, video_id)
    moved = False
    if selected_id:
        # Re-read after insertions: every insert at position 0 shifts prior rows down.
        _, current_rows = api.playlist_video_ids(playlist_id)
        selected_row = current_rows.get(selected_id)
        if selected_row:
            position = (selected_row.get("snippet") or {}).get("position")
            if position != 0:
                api.move_playlist_item_to_top(selected_row, playlist_id)
                moved = True
                _, verified_rows = api.playlist_video_ids(playlist_id)
                verified = verified_rows.get(selected_id)
                if not verified or (verified.get("snippet") or {}).get("position") != 0:
                    raise RuntimeError("Selected video could not be moved to playlist position 0")
        else:
            raise RuntimeError("Selected video was not present in playlist after synchronization")
    return {"added": additions, "moved_selected": moved, "known_before": len(existing_ids)}
