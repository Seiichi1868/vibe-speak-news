"""CNN10 タイトルと文字起こしの対応区間を AI で推定する。"""

from __future__ import annotations

import re

from openai import OpenAI

from services.openai_utils import create_json_chat_completion
from services.youtube import seconds_to_display

_TITLE_DATE_SUFFIX_RE = re.compile(r"\s*\|\s*[A-Za-z]+\s+\d{1,2},?\s+\d{4}\s*$")


def _clean_title(title: str) -> str:
    cleaned = _TITLE_DATE_SUFFIX_RE.sub("", str(title or "").strip()).strip()
    return cleaned or str(title or "").strip()


def _format_snippet_time(sec: float) -> str:
    return seconds_to_display(max(0, int(sec))) or "0:00"


def _build_timed_transcript(snippets: list[dict]) -> str:
    lines = []
    for snippet in snippets:
        text = str(snippet.get("text") or "").strip()
        if not text:
            continue
        start = float(snippet.get("start") or 0)
        lines.append(f"{_format_snippet_time(start)}  {text}")
    return "\n".join(lines)


def _video_duration_sec(snippets: list[dict]) -> int:
    duration = 0
    for snippet in snippets:
        start = float(snippet.get("start") or 0)
        end = start + float(snippet.get("duration") or 0)
        duration = max(duration, int(end))
    return duration


def find_title_segment_in_transcript(
    title: str,
    snippets: list[dict],
    *,
    model: str,
    api_key: str,
) -> dict:
    """動画タイトルに対応するニュース区間の開始・終了秒を推定する。"""
    clean_title = _clean_title(title)
    if not clean_title:
        raise ValueError("動画タイトルがありません。")
    if not snippets:
        raise ValueError("文字起こしが空です。")

    transcript_text = _build_timed_transcript(snippets)
    if not transcript_text.strip():
        raise ValueError("文字起こしが空です。")

    client = OpenAI(api_key=api_key)
    payload = create_json_chat_completion(
        client,
        model,
        [
            {
                "role": "system",
                "content": (
                    "You analyze CNN10 news transcripts. Each video contains multiple short news stories. "
                    "Given an English video title and a timestamped transcript, identify the time range "
                    "where the title's main story is covered in depth (not just a brief intro mention). "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Video title: {clean_title}\n\n"
                    f"Transcript (timestamp at line start in M:SS format):\n{transcript_text}\n\n"
                    "Return JSON with:\n"
                    '- "start_sec": integer seconds where this story begins\n'
                    '- "end_sec": integer seconds where this story ends (before the next story)\n'
                    '- "confidence": "high", "medium", or "low"\n'
                    '- "note": one short English sentence explaining the match'
                ),
            },
        ],
        temperature=0.2,
    )

    start_sec = int(payload.get("start_sec", 0) or 0)
    end_sec = int(payload.get("end_sec", 0) or 0)
    confidence = str(payload.get("confidence") or "medium").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    note = str(payload.get("note") or "").strip()

    max_sec = _video_duration_sec(snippets)
    start_sec = max(0, min(start_sec, max_sec))
    end_sec = max(0, min(end_sec, max_sec))
    if end_sec <= start_sec:
        raise ValueError("AI が有効な時間範囲を返しませんでした。手動で開始・終了時間を設定してください。")

    return {
        "ok": True,
        "title": clean_title,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "start_display": seconds_to_display(start_sec),
        "end_display": seconds_to_display(end_sec),
        "confidence": confidence,
        "note": note,
    }
