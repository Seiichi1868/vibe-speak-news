"""YouTube URL 解析、埋め込み URL 生成、タイトル取得。字幕はブラウザ側で取得。"""

from __future__ import annotations

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
