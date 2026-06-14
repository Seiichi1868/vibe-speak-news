"""CNN10 の YouTube 動画一覧取得（チャンネルページ + 続き読み込み）。"""

from __future__ import annotations

from datetime import datetime
import json
import re
import ssl
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

CNN10_CHANNEL_ID = "UCTOoRgpHTjAQPk6Ak70u-pA"
CNN10_CHANNEL_URL = "https://www.youtube.com/@CNN10/videos"
CNN10_FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CNN10_CHANNEL_ID}"
CNN10_VIDEOS_PAGE = "https://www.youtube.com/@CNN10/videos"
YOUTUBE_THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
INNERTUBE_BROWSE_URL = "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false"
INNERTUBE_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20260101.00.00",
    "hl": "en",
    "gl": "US",
}

_CACHE: dict = {
    "episodes": [],
    "continuation": None,
    "exhausted": False,
    "fetched_at": 0.0,
}
_CACHE_TTL_SEC = 300
_FEED_TITLES: dict[str, str] = {}
_LOCALIZED_TITLE_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def _format_published(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    return dt.strftime("%Y-%m-%d")


def _urlopen(request: Request, timeout: int = 12):
    try:
        return urlopen(request, timeout=timeout)
    except ssl.SSLError:
        pass
    except URLError as exc:
        if not isinstance(exc.reason, ssl.SSLError):
            raise
    return urlopen(request, timeout=timeout, context=ssl._create_unverified_context())


def _fetch_bytes(url: str, timeout: int = 8) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with _urlopen(request, timeout=timeout) as response:
        return response.read()


def _post_json(url: str, payload: dict, timeout: int = 12) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with _urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_yt_initial_data(html: str) -> dict:
    marker = "ytInitialData"
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("CNN10 チャンネルページの解析に失敗しました。")
    start = html.find("{", start)
    depth = 0
    for index, char in enumerate(html[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : index + 1])
    raise RuntimeError("CNN10 チャンネルページの解析に失敗しました。")


def _episode_from_lockup(lockup: dict) -> dict | None:
    video_id = str(lockup.get("contentId") or "").strip()
    if not video_id:
        blob = json.dumps(lockup, ensure_ascii=False)
        match = re.search(r"/vi/([a-zA-Z0-9_-]{11})/", blob)
        video_id = match.group(1) if match else ""
    if not video_id:
        return None

    metadata = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = str(metadata.get("title", {}).get("content", "") or "").strip()
    published = ""
    rows = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
    if rows:
        parts = rows[0].get("metadataParts", [])
        if parts:
            published = str(parts[0].get("text", {}).get("content", "") or "").strip()

    return {
        "title": title or "Untitled",
        "published": published,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "video_id": video_id,
        "thumbnail_url": YOUTUBE_THUMBNAIL_URL.format(video_id=video_id),
    }


def _extract_episodes_and_tokens(data: dict) -> tuple[list[dict], list[str]]:
    episodes: list[dict] = []
    tokens: list[str] = []
    seen: set[str] = set()

    def walk(obj) -> None:
        if isinstance(obj, dict):
            if "lockupViewModel" in obj:
                episode = _episode_from_lockup(obj["lockupViewModel"])
                if episode and episode["video_id"] not in seen:
                    seen.add(episode["video_id"])
                    episodes.append(episode)
            if "continuationItemRenderer" in obj:
                token = (
                    obj["continuationItemRenderer"]
                    .get("continuationEndpoint", {})
                    .get("continuationCommand", {})
                    .get("token")
                )
                if token:
                    tokens.append(token)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return episodes, tokens


def _grid_continuation_token(data: dict) -> str | None:
    token: str | None = None

    def walk(obj, in_grid: bool = False) -> None:
        nonlocal token
        if isinstance(obj, dict):
            if "richGridRenderer" in obj:
                for value in obj["richGridRenderer"].values():
                    walk(value, True)
                return
            if in_grid and "continuationItemRenderer" in obj:
                next_token = (
                    obj["continuationItemRenderer"]
                    .get("continuationEndpoint", {})
                    .get("continuationCommand", {})
                    .get("token")
                )
                if next_token:
                    token = next_token
            for value in obj.values():
                walk(value, in_grid)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, in_grid)

    walk(data)
    return token


def _merge_episodes(existing: list[dict], new_items: list[dict]) -> list[dict]:
    seen = {item["video_id"] for item in existing if item.get("video_id")}
    merged = list(existing)
    for item in new_items:
        video_id = item.get("video_id")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        merged.append(item)
    return merged


def _title_looks_localized(title: str) -> bool:
    return bool(_LOCALIZED_TITLE_RE.search(str(title or "")))


def _enrich_english_titles(episodes: list[dict]) -> list[dict]:
    from services.youtube import fetch_youtube_title

    enriched = []
    for episode in episodes:
        item = dict(episode)
        video_id = str(item.get("video_id") or "").strip()
        feed_title = _FEED_TITLES.get(video_id, "")
        if feed_title:
            item["title"] = feed_title
        elif video_id and _title_looks_localized(item.get("title", "")):
            oembed_title = fetch_youtube_title(video_id)
            if oembed_title:
                item["title"] = oembed_title
        enriched.append(item)
    return enriched


def _enrich_from_feed(episodes: list[dict]) -> list[dict]:
    """RSS フィードの英語タイトルと公開日で上書きできるものは上書きする。"""
    global _FEED_TITLES
    try:
        xml_text = _fetch_bytes(CNN10_FEED_URL)
    except (OSError, URLError):
        return episodes

    root = ET.fromstring(xml_text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    feed_dates: dict[str, str] = {}
    feed_titles: dict[str, str] = {}
    for entry in root.findall("atom:entry", ns):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        if video_id and published:
            feed_dates[video_id] = _format_published(published)
        if video_id and title:
            feed_titles[video_id] = title
    if feed_titles:
        _FEED_TITLES.update(feed_titles)

    enriched = []
    for episode in episodes:
        item = dict(episode)
        video_id = item.get("video_id", "")
        feed_date = feed_dates.get(video_id)
        if feed_date:
            item["published"] = feed_date
        feed_title = feed_titles.get(video_id)
        if feed_title:
            item["title"] = feed_title
        enriched.append(item)
    return enriched


def _fetch_initial_page() -> tuple[list[dict], str | None]:
    html = _fetch_bytes(CNN10_VIDEOS_PAGE, timeout=12).decode("utf-8", errors="replace")
    data = _parse_yt_initial_data(html)
    episodes, _ = _extract_episodes_and_tokens(data)
    token = _grid_continuation_token(data)
    return _enrich_from_feed(episodes), token


def _fetch_continuation(token: str) -> tuple[list[dict], str | None]:
    payload = {
        "context": {"client": INNERTUBE_CLIENT},
        "continuation": token,
    }
    data = _post_json(INNERTUBE_BROWSE_URL, payload)
    episodes, tokens = _extract_episodes_and_tokens(data)
    next_token = _grid_continuation_token(data) or (tokens[-1] if tokens else None)
    return episodes, next_token


def _reset_cache_if_stale() -> None:
    fetched_at = float(_CACHE.get("fetched_at") or 0)
    if fetched_at and (time.time() - fetched_at) < _CACHE_TTL_SEC:
        return
    _CACHE["episodes"] = []
    _CACHE["continuation"] = None
    _CACHE["exhausted"] = False
    _CACHE["fetched_at"] = 0.0


def _ensure_episode_count(required: int) -> None:
    _reset_cache_if_stale()

    if not _CACHE["episodes"] and not _CACHE["exhausted"]:
        episodes, token = _fetch_initial_page()
        _CACHE["episodes"] = episodes
        _CACHE["continuation"] = token
        _CACHE["exhausted"] = not token
        _CACHE["fetched_at"] = time.time()

    while len(_CACHE["episodes"]) < required and not _CACHE["exhausted"]:
        token = _CACHE.get("continuation")
        if not token:
            _CACHE["exhausted"] = True
            break
        try:
            episodes, next_token = _fetch_continuation(token)
        except (OSError, URLError, json.JSONDecodeError, RuntimeError):
            _CACHE["exhausted"] = True
            break
        if not episodes:
            _CACHE["exhausted"] = True
            break
        _CACHE["episodes"] = _merge_episodes(_CACHE["episodes"], episodes)
        _CACHE["continuation"] = next_token
        _CACHE["exhausted"] = not next_token
        _CACHE["fetched_at"] = time.time()


def fetch_cnn10_episodes(offset: int = 0, limit: int = 10) -> dict:
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 10), 30))
    required = offset + limit

    try:
        _ensure_episode_count(required)
    except (OSError, URLError, RuntimeError) as exc:
        raise RuntimeError(f"CNN10 の動画一覧を取得できませんでした: {exc}") from exc

    all_episodes = _CACHE["episodes"]
    page = _enrich_english_titles(all_episodes[offset : offset + limit])
    has_more = len(all_episodes) > offset + limit or not _CACHE["exhausted"]

    return {
        "episodes": page,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + len(page),
        "has_more": has_more,
        "total_loaded": len(all_episodes),
    }
