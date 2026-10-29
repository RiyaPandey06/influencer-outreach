"""Thin YouTube Data API v3 client (official, ToS-compliant data source)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterator

import requests

from .utils import ApiError, log, request_json

BASE = "https://www.googleapis.com/youtube/v3"


class QuotaExceeded(Exception):
    pass


class YouTubeClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is not set")
        self.key = api_key
        self.session = session or requests.Session()

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.key
        try:
            return request_json("GET", f"{BASE}/{path}", session=self.session, params=params)
        except ApiError as exc:
            if exc.status == 403 and "quota" in exc.body.lower():
                raise QuotaExceeded("YouTube API daily quota exhausted") from exc
            raise

    def search_channels(self, query: str, max_pages: int = 3, region_code: str | None = None,
                        relevance_language: str | None = None) -> Iterator[list[str]]:
        """Yield lists of channel ids, one list per result page."""
        token = None
        for _ in range(max_pages):
            params = dict(part="snippet", type="channel", q=query, maxResults=50)
            if token:
                params["pageToken"] = token
            if region_code:
                params["regionCode"] = region_code
            if relevance_language:
                params["relevanceLanguage"] = relevance_language
            data = self._get("search", **params)
            ids = [it.get("snippet", {}).get("channelId") or it.get("id", {}).get("channelId")
                   for it in data.get("items", [])]
            yield [i for i in ids if i]
            token = data.get("nextPageToken")
            if not token:
                break

    def get_channels(self, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            data = self._get("channels", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]),
                             maxResults=50)
            out.extend(data.get("items", []))
        return out

    def get_recent_videos(self, uploads_playlist: str, n: int = 10) -> list[dict]:
        """Return normalised recent videos (title, date, views, likes, comments, tags)."""
        if not uploads_playlist:
            return []
        try:
            pl = self._get("playlistItems", part="contentDetails", playlistId=uploads_playlist, maxResults=n)
        except ApiError as exc:
            log.warning("Could not read uploads playlist %s: %s", uploads_playlist, exc)
            return []
        vids = [it["contentDetails"]["videoId"] for it in pl.get("items", []) if "contentDetails" in it]
        if not vids:
            return []
        data = self._get("videos", part="snippet,statistics", id=",".join(vids), maxResults=n)
        videos = []
        for v in data.get("items", []):
            st, sn = v.get("statistics", {}), v.get("snippet", {})
            videos.append({
                "id": v["id"],
                "title": sn.get("title", ""),
                "published": sn.get("publishedAt"),
                "views": _to_int(st.get("viewCount")),
                "likes": _to_int(st.get("likeCount")),       # None if the creator hides likes
                "comments": _to_int(st.get("commentCount")),  # None if comments disabled
                "tags": sn.get("tags", []),
                "url": f"https://www.youtube.com/watch?v={v['id']}",
            })
        videos.sort(key=lambda x: x["published"] or "", reverse=True)
        return videos


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_channel(item: dict, query: str) -> dict:
    """Convert a channels.list item into an `influencers` row."""
    sn, st = item.get("snippet", {}), item.get("statistics", {})
    cid = item["id"]
    hidden = bool(st.get("hiddenSubscriberCount"))
    followers = None if hidden else _to_int(st.get("subscriberCount"))
    return {
        "channel_id": cid,
        "name": sn.get("title") or "Not Found",
        "platform": "YouTube",
        "profile_url": f"https://www.youtube.com/channel/{cid}",
        "handle": sn.get("customUrl"),
        "followers": followers,
        "subs_hidden": 1 if hidden else 0,
        "country": sn.get("country"),
        "description": sn.get("description", ""),
        "uploads_playlist": item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "video_count": _to_int(st.get("videoCount")),
        "discovery_query": query,
        "discovered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def compute_engagement(videos: list[dict], min_videos: int = 3) -> tuple[float | None, str]:
    """Average per-video (likes + comments) / views, in percent. Never estimated: None if data is missing."""
    rates = []
    for v in videos:
        if v["likes"] is None or not v["views"]:
            continue
        rates.append((v["likes"] + (v["comments"] or 0)) / v["views"] * 100)
    if len(rates) < min_videos:
        return None, f"Not Available (only {len(rates)} recent videos expose likes/views; need {min_videos})"
    return round(sum(rates) / len(rates), 2), f"avg of {len(rates)} recent videos: (likes+comments)/views"
