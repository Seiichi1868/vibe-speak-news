"""YouTube URL 解析、埋め込み URL 生成、字幕（文字起こし）取得。"""

import json
import re
import ssl
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import quote, unquote

# 11桁の YouTube 動画 ID
_VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")

# URL から「11桁の動画IDだけ」を抜く（?si= や &t= などは無視）
_VIDEO_ID_FROM_URL_RE = re.compile(
    r"(?:v=|vi=|/)([0-9A-Za-z_-]{11})(?=$|[^0-9A-Za-z_-])",
    re.IGNORECASE,
)


def build_youtube_embed_url(
    video_id: str,
    start_sec: int = 0,
    end_sec: int = 0,
    origin: str = "",
    subtitles_enabled: bool = False,
) -> str:
    """モバイル対応の YouTube 埋め込み URL を生成する。"""
    if not video_id:
        return ""
    params = [
        f"start={max(0, int(start_sec))}",
        "playsinline=1",
        "rel=0",
        "modestbranding=1",
        "enablejsapi=1",
        "fs=1",
        "iv_load_policy=3",
    ]
    if end_sec and int(end_sec) > int(start_sec):
        params.append(f"end={int(end_sec)}")
    if subtitles_enabled:
        params.extend(["cc_load_policy=1", "cc_lang_pref=en"])
    if origin:
        origin_clean = origin.rstrip("/")
        params.append(f"origin={quote(origin_clean, safe='')}")
        params.append(f"widget_referrer={quote(origin_clean, safe='')}")
    return f"https://www.youtube.com/embed/{video_id}?{'&'.join(params)}"


def extract_video_id(url: str) -> str:
    """watch / youtu.be / shorts / embed などから 11 桁の動画 ID を抽出。"""
    if not url or not str(url).strip():
        raise ValueError("YouTube URL または動画 ID を入力してください。")

    raw = str(url).strip()
    raw = unquote(raw)
    raw = raw.split("#", 1)[0]

    if _VIDEO_ID_PATTERN.fullmatch(raw):
        return raw

    match = _VIDEO_ID_FROM_URL_RE.search(raw)
    if match:
        candidate = match.group(1)
        if _VIDEO_ID_PATTERN.fullmatch(candidate):
            return candidate

    raise ValueError(
        "有効な YouTube URL または 11 桁の動画 ID を入力してください。"
        "（watch?v= / youtu.be/ / shorts/ に対応）"
    )


def _urlopen(request: Request, timeout: int = 12):
    try:
        return urlopen(request, timeout=timeout)
    except ssl.SSLError:
        pass
    except URLError as exc:
        if not isinstance(exc.reason, ssl.SSLError):
            raise
    return urlopen(request, timeout=timeout, context=ssl._create_unverified_context())


def fetch_youtube_title(url_or_video_id: str) -> str:
    """YouTube oEmbed から動画タイトルを取得。失敗時は空文字を返す。"""
    raw = (url_or_video_id or "").strip()
    if not raw:
        return ""

    try:
        video_id = extract_video_id(raw)
    except ValueError:
        video_id = ""

    watch_url = raw if raw.startswith(("http://", "https://")) else f"https://www.youtube.com/watch?v={video_id or raw}"
    endpoint = f"https://www.youtube.com/oembed?format=json&url={quote(watch_url, safe='')}"
    try:
        request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0"})
        with _urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return ""

    return str(data.get("title") or "").strip()


def parse_time_to_seconds(value: str) -> int:
    """Parse '01:20', '80秒', '80', '1:02:30' into seconds."""
    if value is None:
        raise ValueError("時間を入力してください。")

    text = str(value).strip()
    if not text:
        raise ValueError("時間を入力してください。")

    text = re.sub(r"\s*秒\s*$", "", text, flags=re.IGNORECASE).strip()

    if re.fullmatch(r"\d+", text):
        return int(text)

    if ":" in text:
        parts = [int(p) for p in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return hours * 3600 + minutes * 60 + seconds
        raise ValueError("時刻形式が正しくありません（例: 01:20 または 80）。")

    raise ValueError("時刻形式が正しくありません（例: 01:20 または 80秒）。")


def seconds_to_display(sec: int) -> str:
    if not sec:
        return ""
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _format_transcript_timestamp(sec: float) -> str:
    s = max(0, int(sec))
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_transcript_for_script(snippets) -> str:
    lines = []
    current = []
    for snippet in snippets:
        text = str(getattr(snippet, "text", "") or "").strip()
        if not text:
            continue
        current.append(text)
        if text.endswith((".", "!", "?")):
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _format_transcript_timed(snippets) -> str:
    lines = []
    for snippet in snippets:
        text = str(getattr(snippet, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(snippet, "start", 0) or 0)
        lines.append(f"{_format_transcript_timestamp(start)}  {text}")
    return "\n".join(lines)


def _snippets_to_dicts(snippets) -> list[dict]:
    items = []
    for snippet in snippets:
        text = str(getattr(snippet, "text", "") or "").strip()
        if not text:
            continue
        items.append(
            {
                "start": round(float(getattr(snippet, "start", 0) or 0), 3),
                "duration": round(float(getattr(snippet, "duration", 0) or 0), 3),
                "text": text,
            }
        )
    return items


def _filter_snippets_by_range(snippets, start_sec: int, end_sec: int):
    if end_sec <= start_sec:
        return snippets
    filtered = []
    for snippet in snippets:
        snippet_start = float(getattr(snippet, "start", 0) or 0)
        duration = float(getattr(snippet, "duration", 0) or 0)
        snippet_end = snippet_start + duration
        if snippet_start < end_sec and snippet_end > start_sec:
            filtered.append(snippet)
    return filtered


def fetch_youtube_transcript(
    video_id: str,
    languages: list[str] | None = None,
    start_sec: int | None = None,
    end_sec: int | None = None,
) -> dict:
    """YouTube の公開文字起こしを取得する（非公式 API。取得できない動画もある）。"""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApiException,
    )

    raw = str(video_id or "").strip()
    if not raw:
        raise ValueError("動画 ID を指定してください。")

    vid = raw if _VIDEO_ID_PATTERN.fullmatch(raw) else extract_video_id(raw)
    langs = languages or ["en"]

    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(vid, languages=langs)
    except TranscriptsDisabled as exc:
        raise ValueError("この動画では文字起こしが無効になっています。") from exc
    except NoTranscriptFound as exc:
        raise ValueError("英語の文字起こしが見つかりませんでした。") from exc
    except VideoUnavailable as exc:
        raise ValueError("動画が見つからないか、再生できません。") from exc
    except YouTubeTranscriptApiException as exc:
        raise ValueError(f"YouTube から文字起こしを取得できませんでした: {exc}") from exc

    snippets = fetched
    range_applied = False
    if start_sec is not None and end_sec is not None and int(end_sec) > int(start_sec):
        snippets = _filter_snippets_by_range(fetched, int(start_sec), int(end_sec))
        range_applied = True
        if not snippets:
            raise ValueError("指定した時間範囲に文字起こしがありません。")

    all_snippets = _snippets_to_dicts(fetched)
    active_snippets = _snippets_to_dicts(snippets)

    return {
        "video_id": vid,
        "language": fetched.language,
        "language_code": fetched.language_code,
        "is_generated": fetched.is_generated,
        "script": _format_transcript_for_script(snippets),
        "script_timed": _format_transcript_timed(snippets),
        "snippets": active_snippets,
        "all_snippets": all_snippets if range_applied else active_snippets,
        "range_applied": range_applied,
        "start_sec": int(start_sec) if range_applied else None,
        "end_sec": int(end_sec) if range_applied else None,
    }
