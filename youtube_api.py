"""Minimal YouTube Data API v3 client using OAuth refresh credentials."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
SCOPES = ("https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl")
YOUTUBE_API_ERROR_REASONS = {
    "channelNotFound": "channel was not found",
    "channelForbidden": "channel does not support this request or is not accessible",
    "manualSortRequired": "manual sort is required for position changes",
    "invalidPlaylistItemPosition": "invalid playlist item position",
    "invalidResourceType": "invalid resource type",
    "invalidContentDetails": "invalid content details",
    "playlistOperationUnsupported": "playlist operation is unsupported",
    "videoAlreadyInAnotherSeriesPlaylist": "video is already in another series playlist",
    "playlistIdRequired": "playlist ID is required",
    "resourceIdRequired": "resource ID is required",
    "channelIdRequired": "channel ID is required",
    "playlistItemsNotAccessible": "playlist items are not accessible to this account",
    "forbidden": "the account is not allowed to perform this operation",
    "insufficientPermissions": "the granted OAuth permissions are insufficient",
    "quotaExceeded": "YouTube API quota has been exceeded",
    "playlistNotFound": "playlist was not found or is not accessible",
    "videoNotFound": "video was not found or is not accessible",
    "accessNotConfigured": "YouTube Data API is not enabled for this project",
}


def credentials_available(env=os.environ) -> bool:
    return all(env.get(key, "").strip() for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))


def credentials_present(env=os.environ) -> bool:
    return any(env.get(key, "").strip() for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))


class YouTubeAPI:
    def __init__(self, env=os.environ, opener=urllib.request.urlopen):
        self.env = env
        self.opener = opener
        self._token = None

    def _json_request(self, request):
        api_error = None
        try:
            with self.opener(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Only a whitelisted machine reason and status are safe to surface.
            body = b""
            try:
                body = exc.read()
            except OSError:
                pass
            api_error = self._youtube_api_error_message(exc.code, body)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise RuntimeError(f"YouTube API request failed ({type(exc).__name__})") from None
        if api_error:
            # Raise after leaving the except block so the HTTPError is not retained as context.
            raise RuntimeError(api_error)

    @staticmethod
    def _youtube_api_error_message(status: int, body: bytes) -> str:
        """Expose only allowlisted YouTube API reason codes; discard all body text."""
        try:
            payload = json.loads(body.decode("utf-8"))
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            entries = error.get("errors", []) if isinstance(error, dict) else []
            reasons = [entry.get("reason") for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
            reason = next((value for value in reasons if isinstance(value, str) and value in YOUTUBE_API_ERROR_REASONS), None)
        except (UnicodeDecodeError, json.JSONDecodeError):
            reason = None
        if reason == "manualSortRequired":
            return f"YouTube API HTTP {status} (manualSortRequired): プレイリストの並べ替えを「手動」に設定してください。"
        if reason:
            return f"YouTube API HTTP {status} ({reason}): {YOUTUBE_API_ERROR_REASONS[reason]}"
        return f"YouTube API returned HTTP {status}; error details were withheld."

    def access_token(self) -> str:
        if self._token:
            return self._token
        if not credentials_available(self.env):
            raise RuntimeError("YouTube OAuth credentials are not configured")
        body = urllib.parse.urlencode({
            "client_id": self.env["YOUTUBE_CLIENT_ID"].strip(),
            "client_secret": self.env["YOUTUBE_CLIENT_SECRET"].strip(),
            "refresh_token": self.env["YOUTUBE_REFRESH_TOKEN"].strip(),
            "grant_type": "refresh_token",
        }).encode("utf-8")
        request = urllib.request.Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener(request, timeout=25) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = b""
            try:
                raw = exc.read()
            except OSError:
                pass
            raise RuntimeError(self._oauth_error_message(exc.code, raw)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Report only a stable exception category; URLError.reason may contain URLs or details.
            raise RuntimeError(f"OAuth token refresh could not reach Google ({type(exc).__name__})") from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError(f"OAuth token response was not valid JSON (HTTP {status})") from None
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise RuntimeError(self._oauth_error_message(status, raw))
        self._token = token
        return token

    @staticmethod
    def _oauth_error_message(status: int, body: bytes) -> str:
        """Translate only safe, documented error codes; never echo response text."""
        try:
            decoded = json.loads(body.decode("utf-8"))
            code = decoded.get("error") if isinstance(decoded, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            code = None
        messages = {
            "invalid_grant": "OAuth refresh failed: invalid_grant — refresh token may be expired or revoked, or paired with a different OAuth client. Compare all three current secret values before reauthorizing.",
            "invalid_client": "OAuth refresh failed: invalid_client — check that the client ID and secret are the matching pair from the current Desktop OAuth client.",
            "unauthorized_client": "OAuth refresh failed: unauthorized_client — this OAuth client or grant is not authorized for the requested flow.",
            "access_denied": "OAuth refresh failed: access_denied — authorization was denied; approve the requested YouTube access for the intended account.",
            "invalid_request": "OAuth refresh failed: invalid_request — the token request was rejected as malformed; check the OAuth client and refresh token values.",
        }
        if isinstance(code, str) and code in messages:
            return messages[code]
        return f"OAuth token refresh failed (HTTP {status}); Google returned an unrecognized or empty error response. No response details were exposed."

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

    def recent_channel_videos(self, channel: dict, max_results: int = 15) -> list[dict]:
        """Read a channel's most recent uploads through its API-provided uploads playlist."""
        result = self.call("GET", "/channels", {"part": "contentDetails", "id": channel["id"]})
        items = result.get("items") or []
        if not items:
            raise RuntimeError("API_CHANNEL_NOT_FOUND")
        content = items[0].get("contentDetails") or {}
        uploads_id = (content.get("relatedPlaylists") or {}).get("uploads")
        if not uploads_id:
            raise RuntimeError("API_UPLOADS_PLAYLIST_UNAVAILABLE")
        limit = min(50, max(1, int(max_results)))
        page = self.call("GET", "/playlistItems", {
            "part": "snippet,contentDetails", "playlistId": uploads_id,
            "maxResults": limit,
        })
        videos = []
        for item in (page.get("items") or [])[:limit]:
            snippet = item.get("snippet") or {}
            details = item.get("contentDetails") or {}
            video_id = details.get("videoId")
            title = (snippet.get("title") or "").strip()
            published = details.get("videoPublishedAt") or snippet.get("publishedAt") or ""
            if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not title:
                continue
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
            except (AttributeError, ValueError):
                continue
            videos.append({
                "video_id": video_id,
                "title": title,
                "published": published_at.astimezone(timezone.utc),
                "channel": channel["name"],
                "channel_id": channel["id"],
                "url": "https://www.youtube.com/watch?v=" + video_id,
            })
        return videos

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
