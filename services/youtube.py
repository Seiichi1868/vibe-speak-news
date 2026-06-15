"""YouTube URL 解析、埋め込み URL 生成、字幕（文字起こし）取得。"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
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

_DEFAULT_SUBTITLE_LANGS = ("ja", "en")
_SUBTITLE_FORMAT_PRIORITY = ("json3", "vtt", "srv3", "ttml", "srt")
_LANGUAGE_LABELS = {
    "ja": "Japanese",
    "en": "English",
}


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


def _format_transcript_for_script(snippets: list[dict]) -> str:
    lines = []
    current = []
    for snippet in snippets:
        text = str(snippet.get("text") or "").strip()
        if not text:
            continue
        current.append(text)
        if text.endswith((".", "!", "?")):
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _format_transcript_timed(snippets: list[dict]) -> str:
    lines = []
    for snippet in snippets:
        text = str(snippet.get("text") or "").strip()
        if not text:
            continue
        start = float(snippet.get("start") or 0)
        lines.append(f"{_format_transcript_timestamp(start)}  {text}")
    return "\n".join(lines)


def _normalize_snippets(snippets: list[dict]) -> list[dict]:
    items = []
    for snippet in snippets:
        text = str(snippet.get("text") or "").strip()
        if not text:
            continue
        items.append(
            {
                "start": round(float(snippet.get("start") or 0), 3),
                "duration": round(float(snippet.get("duration") or 0), 3),
                "text": text,
            }
        )
    return items


def _filter_snippets_by_range(snippets: list[dict], start_sec: int, end_sec: int) -> list[dict]:
    if end_sec <= start_sec:
        return snippets
    filtered = []
    for snippet in snippets:
        snippet_start = float(snippet.get("start") or 0)
        duration = float(snippet.get("duration") or 0)
        snippet_end = snippet_start + duration
        if snippet_start < end_sec and snippet_end > start_sec:
            filtered.append(snippet)
    return filtered


def _language_label(code: str) -> str:
    base = (code or "").split("-")[0].lower()
    return _LANGUAGE_LABELS.get(base, code or "Unknown")


def _build_ytdlp_opts() -> dict:
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": list(_DEFAULT_SUBTITLE_LANGS),
        "quiet": True,
        "no_warnings": True,
        "sleep_interval_requests": 1,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }
    proxy = (
        (os.environ.get("YOUTUBE_PROXY_URL") or "").strip()
        or (os.environ.get("HTTPS_PROXY") or "").strip()
        or (os.environ.get("HTTP_PROXY") or "").strip()
    )
    if proxy:
        opts["proxy"] = proxy
    return opts


def _lang_matches(candidate: str, preferred: str) -> bool:
    candidate = (candidate or "").lower()
    preferred = (preferred or "").lower()
    return candidate == preferred or candidate.startswith(f"{preferred}-")


def _pick_subtitle_track(
    manual: dict,
    automatic: dict,
    languages: list[str],
) -> tuple[str, list[dict], bool] | None:
    for lang in languages:
        if lang in manual and manual[lang]:
            return lang, manual[lang], False
        for key, tracks in manual.items():
            if _lang_matches(key, lang) and tracks:
                return key, tracks, False

    for lang in languages:
        if lang in automatic and automatic[lang]:
            return lang, automatic[lang], True
        for key, tracks in automatic.items():
            if _lang_matches(key, lang) and tracks:
                return key, tracks, True

    return None


def _pick_subtitle_url(tracks: list[dict]) -> tuple[str, str]:
    by_ext = {str(track.get("ext") or ""): track for track in tracks if track.get("url")}
    for ext in _SUBTITLE_FORMAT_PRIORITY:
        track = by_ext.get(ext)
        if track and track.get("url"):
            return str(track["url"]), ext

    for track in tracks:
        if track.get("url"):
            return str(track["url"]), str(track.get("ext") or "unknown")
    raise ValueError("字幕 URL を取得できませんでした。")


def _fetch_subtitle_text(ydl, url: str) -> str:
    response, _ = ydl.urlopen(url)
    return response.read().decode("utf-8", errors="replace")


def _parse_vtt_timestamp(value: str) -> float:
    value = value.strip()
    if not value:
        return 0.0
    if value.endswith("Z"):
        value = value[:-1]
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds.replace(",", "."))
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds.replace(",", "."))
    except ValueError:
        return 0.0
    return 0.0


def _strip_vtt_tags(text: str) -> str:
    text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.replace("\n", " ").split()).strip()


def _parse_json3_subtitle(text: str) -> list[dict]:
    data = json.loads(text)
    snippets = []
    for event in data.get("events") or []:
        if "segs" not in event:
            continue
        parts = [str(seg.get("utf8") or "") for seg in event.get("segs") or []]
        body = "".join(parts).replace("\n", " ").strip()
        if not body:
            continue
        start_ms = float(event.get("tStartMs") or 0)
        duration_ms = float(event.get("dDurationMs") or 0)
        snippets.append(
            {
                "start": start_ms / 1000.0,
                "duration": max(duration_ms / 1000.0, 0.1),
                "text": body,
            }
        )
    return snippets


def _parse_vtt_subtitle(text: str) -> list[dict]:
    snippets = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        time_line = next((line for line in lines if "-->" in line), "")
        if not time_line:
            continue

        start_raw, end_raw = [part.strip() for part in time_line.split("-->", 1)]
        start = _parse_vtt_timestamp(start_raw)
        end = _parse_vtt_timestamp(end_raw.split()[0])
        text_lines = [line for line in lines if line != time_line and "-->" not in line and not line.isdigit()]
        body = _strip_vtt_tags(" ".join(text_lines))
        if not body:
            continue
        snippets.append(
            {
                "start": start,
                "duration": max(end - start, 0.1),
                "text": body,
            }
        )
    return snippets


def _parse_subtitle_content(text: str, ext: str) -> list[dict]:
    ext = (ext or "").lower()
    if ext == "json3":
        snippets = _parse_json3_subtitle(text)
    elif ext in {"vtt", "srv3", "ttml", "srt"}:
        snippets = _parse_vtt_subtitle(text)
    else:
        try:
            snippets = _parse_json3_subtitle(text)
        except json.JSONDecodeError:
            snippets = _parse_vtt_subtitle(text)

    if not snippets:
        raise ValueError("字幕データを解析できませんでした。")
    return snippets


def _translate_ytdlp_error(exc: Exception) -> ValueError:
    message = str(exc or "").lower()
    if any(token in message for token in ("429", "too many requests", "rate limit")):
        return ValueError("YouTube へのリクエストが制限されています。しばらく待ってから再試行してください。")
    if any(token in message for token in ("blocked", "cloud provider", "sign in to confirm")):
        return ValueError(
            "YouTube がサーバーからのアクセスをブロックしました。"
            "時間をおいて再試行するか、環境変数 YOUTUBE_PROXY_URL の設定を検討してください。"
        )
    if "private video" in message or "video unavailable" in message:
        return ValueError("動画が見つからないか、再生できません。")
    if "subtitles" in message and "not available" in message:
        return ValueError("日本語・英語の字幕が見つかりませんでした。")
    return ValueError(f"YouTube から字幕を取得できませんでした: {exc}")


def _fetch_subtitles_with_ytdlp(video_id: str, languages: list[str]) -> tuple[list[dict], str, bool]:
    import yt_dlp

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(_build_ytdlp_opts()) as ydl:
            info = ydl.extract_info(watch_url, download=False)
            if not info:
                raise ValueError("動画情報を取得できませんでした。")

            manual = info.get("subtitles") or {}
            automatic = info.get("automatic_captions") or {}
            picked = _pick_subtitle_track(manual, automatic, languages)
            if not picked:
                raise ValueError("日本語・英語の字幕が見つかりませんでした。")

            language_code, tracks, is_generated = picked
            subtitle_url, subtitle_ext = _pick_subtitle_url(tracks)

            raw_text = None
            last_error = None
            for attempt in range(3):
                try:
                    raw_text = _fetch_subtitle_text(ydl, subtitle_url)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2 and "429" in str(exc):
                        time.sleep(2 ** attempt)
                        continue
                    if hasattr(exc, "__class__") and exc.__class__.__name__ == "DownloadError":
                        raise _translate_ytdlp_error(exc) from exc
                    raise ValueError(f"字幕ファイルの取得に失敗しました: {exc}") from exc
            if raw_text is None and last_error is not None:
                if "429" in str(last_error):
                    raise _translate_ytdlp_error(last_error)
                raise ValueError(f"字幕ファイルの取得に失敗しました: {last_error}")
    except yt_dlp.utils.DownloadError as exc:
        raise _translate_ytdlp_error(exc) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise _translate_ytdlp_error(exc) from exc

    snippets = _parse_subtitle_content(raw_text, subtitle_ext)
    return snippets, language_code, is_generated


def fetch_youtube_transcript(
    video_id: str,
    languages: list[str] | None = None,
    start_sec: int | None = None,
    end_sec: int | None = None,
) -> dict:
    """yt-dlp で YouTube 字幕を取得する（動画本体はダウンロードしない）。"""
    raw = str(video_id or "").strip()
    if not raw:
        raise ValueError("動画 ID を指定してください。")

    vid = raw if _VIDEO_ID_PATTERN.fullmatch(raw) else extract_video_id(raw)
    langs = languages or list(_DEFAULT_SUBTITLE_LANGS)

    fetched_snippets, language_code, is_generated = _fetch_subtitles_with_ytdlp(vid, langs)

    snippets = fetched_snippets
    range_applied = False
    if start_sec is not None and end_sec is not None and int(end_sec) > int(start_sec):
        snippets = _filter_snippets_by_range(fetched_snippets, int(start_sec), int(end_sec))
        range_applied = True
        if not snippets:
            raise ValueError("指定した時間範囲に文字起こしがありません。")

    all_snippets = _normalize_snippets(fetched_snippets)
    active_snippets = _normalize_snippets(snippets)

    return {
        "video_id": vid,
        "language": _language_label(language_code),
        "language_code": language_code,
        "is_generated": is_generated,
        "script": _format_transcript_for_script(active_snippets),
        "script_timed": _format_transcript_timed(active_snippets),
        "snippets": active_snippets,
        "all_snippets": all_snippets if range_applied else active_snippets,
        "range_applied": range_applied,
        "start_sec": int(start_sec) if range_applied else None,
        "end_sec": int(end_sec) if range_applied else None,
    }
