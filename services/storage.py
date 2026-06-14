import json
import re
import threading
import uuid
import io
from copy import deepcopy
from datetime import datetime, timezone

import openpyxl

from config import CEFR_LEVELS, DATA_DIR, STATE_FILE

_lock = threading.Lock()
ROSTER_FILE = DATA_DIR / "roster.json"
SUBMISSIONS_FILE = DATA_DIR / "submissions.json"

# アプリ全体のデフォルト評価基準（クラス側が空欄のときに使用）
DEFAULT_EVALUATION_CRITERIA = {
    "A1": (
        "CEFR A1: とても短い基本文で、動画の中心語や人物・出来事を少し伝えられるかを見る。"
        "完全な文でなくても、聞き取れた重要語を使って内容に触れられているかを重視。"
    ),
    "A2": (
        "CEFR A2: キーワードと主要事実の把握を重視。"
        "短い文で要点が伝わるか、重要語が含まれるかを見る。"
    ),
    "B1": (
        "CEFR B1: 構成と流れを重視。"
        "導入・要点・結び、接続表現、情報の整理を見る。"
    ),
    "B2": (
        "CEFR B2: パラフレーズと論理展開を重視。"
        "言い換え、因果・対比、分析的な要約かを見る。"
    ),
}

DEFAULT_CLASS_CURRENT = {
    "source_url": "",
    "video_id": "",
    "start_seconds": 0,
    "end_seconds": 0,
    "script": "",
    "evaluation_criteria": {level: "" for level in CEFR_LEVELS},
    "prep_timer_seconds": 60,
    "record_timer_seconds": 60,
    "timers_visible": True,
    "subtitles_enabled": False,
}

DEFAULT_STATE = {
    "display_language": "ja",
    "ai_model": "gpt-4o-mini",
    "openai_api_key": "",
    "default_evaluation_criteria": deepcopy(DEFAULT_EVALUATION_CRITERIA),
    "active_class_id": "",
    "classes": {},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_id(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9\u3040-\u30ff\u4e00-\u9fff]+", "-", name.strip()).strip("-")
    if not base:
        base = "class"
    return f"{base}_{uuid.uuid4().hex[:8]}"


def _empty_criteria() -> dict:
    return {level: "" for level in CEFR_LEVELS}


def _coerce_nonnegative_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def lesson_key(video_id: str, start_seconds: int, end_seconds: int) -> str:
    return f"{str(video_id or '').strip()}:{_coerce_nonnegative_int(start_seconds)}:{_coerce_nonnegative_int(end_seconds)}"


def lesson_title_display(title: str = "", video_id: str = "", fallback: str = "未分類") -> str:
    title = str(title or "").strip()
    video_id = str(video_id or "").strip()
    if title and title != video_id:
        return title
    if video_id:
        return f"{video_id}（動画タイトル未指定）"
    return fallback


def current_lesson_identity(cls: dict | None) -> dict:
    current = (cls or {}).get("current") or {}
    video_id = str(current.get("video_id") or "").strip()
    start_seconds = _coerce_nonnegative_int(current.get("start_seconds"), 0)
    end_seconds = _coerce_nonnegative_int(current.get("end_seconds"), 0)
    key = lesson_key(video_id, start_seconds, end_seconds)
    return {
        "lesson_key": key,
        "lesson_title": lesson_title_display(current.get("title", ""), video_id, "現在の授業"),
        "lesson_video_id": video_id,
        "lesson_start_seconds": start_seconds,
        "lesson_end_seconds": end_seconds,
    }


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_criteria(raw: dict | None) -> dict:
    merged = _empty_criteria()
    if isinstance(raw, dict):
        for level in CEFR_LEVELS:
            merged[level] = str(raw.get(level) or "").strip()
    return merged


def _normalize_current(raw: dict | None) -> dict:
    current = deepcopy(DEFAULT_CLASS_CURRENT)
    if not isinstance(raw, dict):
        return current
    current.update(
        {
            "source_url": str(raw.get("source_url") or "").strip(),
            "video_id": str(raw.get("video_id") or "").strip(),
            "start_seconds": _coerce_nonnegative_int(raw.get("start_seconds"), 0),
            "end_seconds": _coerce_nonnegative_int(raw.get("end_seconds"), 0),
            "script": str(raw.get("script") or "").strip(),
            "evaluation_criteria": _normalize_criteria(raw.get("evaluation_criteria")),
            "prep_timer_seconds": _coerce_nonnegative_int(raw.get("prep_timer_seconds"), 0),
            "record_timer_seconds": _coerce_nonnegative_int(raw.get("record_timer_seconds"), 60),
            "timers_visible": bool(raw.get("timers_visible", True)),
            "subtitles_enabled": bool(raw.get("subtitles_enabled", False)),
        }
    )
    return current


def _normalize_class(class_id: str, raw: dict) -> dict:
    archive = raw.get("archive") if isinstance(raw.get("archive"), list) else []
    normalized_archive = []
    for item in archive:
        if not isinstance(item, dict):
            continue
        normalized_archive.append(
            {
                "title": str(item.get("title") or item.get("video_title") or item.get("video_id") or "無題のアーカイブ").strip(),
                "archived_at": str(item.get("archived_at") or _now_iso()),
                "source_url": str(item.get("source_url") or "").strip(),
                "video_id": str(item.get("video_id") or "").strip(),
                "start_seconds": _coerce_nonnegative_int(item.get("start_seconds"), 0),
                "end_seconds": _coerce_nonnegative_int(item.get("end_seconds"), 0),
                "script": str(item.get("script") or "").strip(),
                "evaluation_criteria": _normalize_criteria(item.get("evaluation_criteria")),
                "prep_timer_seconds": _coerce_nonnegative_int(item.get("prep_timer_seconds"), 0),
                "record_timer_seconds": _coerce_nonnegative_int(item.get("record_timer_seconds"), 60),
                "timers_visible": bool(item.get("timers_visible", True)),
                "subtitles_enabled": bool(item.get("subtitles_enabled", False)),
            }
        )
    return {
        "id": class_id,
        "name": str(raw.get("name") or class_id).strip() or class_id,
        "created_at": str(raw.get("created_at") or _now_iso()),
        "current": _normalize_current(raw.get("current")),
        "archive": normalized_archive,
    }


def _migrate_legacy_state(data: dict) -> dict:
    """旧形式（単一 video / class_code）→ 複数クラス形式へ変換。"""
    state = deepcopy(DEFAULT_STATE)

    for key in ("display_language", "ai_model", "openai_api_key", "active_class_id"):
        if key in data and data[key] is not None:
            state[key] = data[key]

    if isinstance(data.get("default_evaluation_criteria"), dict):
        state["default_evaluation_criteria"] = _normalize_criteria(data["default_evaluation_criteria"])
        for level in CEFR_LEVELS:
            if not state["default_evaluation_criteria"][level]:
                state["default_evaluation_criteria"][level] = DEFAULT_EVALUATION_CRITERIA[level]

    classes_raw = data.get("classes")
    if isinstance(classes_raw, dict) and classes_raw:
        for cid, cls in classes_raw.items():
            if isinstance(cls, dict):
                state["classes"][cid] = _normalize_class(cid, cls)
        if state["active_class_id"] not in state["classes"] and state["classes"]:
            state["active_class_id"] = next(iter(state["classes"]))
        return state

    legacy_video = data.get("video") if isinstance(data.get("video"), dict) else {}
    class_name = (data.get("class_code") or "").strip() or "デフォルトクラス"
    class_id = _slug_id(class_name)
    current = _normalize_current(legacy_video)
    state["classes"][class_id] = {
        "id": class_id,
        "name": class_name,
        "created_at": _now_iso(),
        "current": current,
        "archive": [],
    }
    state["active_class_id"] = class_id
    return state


def _normalize_state(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return deepcopy(DEFAULT_STATE)

    classes_raw = data.get("classes")
    if isinstance(classes_raw, dict) and classes_raw:
        merged = deepcopy(DEFAULT_STATE)
        for key in ("display_language", "ai_model", "openai_api_key", "active_class_id"):
            if key in data and data[key] is not None:
                merged[key] = data[key]
        if isinstance(data.get("default_evaluation_criteria"), dict):
            merged["default_evaluation_criteria"] = _normalize_criteria(data["default_evaluation_criteria"])
            for level in CEFR_LEVELS:
                if not merged["default_evaluation_criteria"][level]:
                    merged["default_evaluation_criteria"][level] = DEFAULT_EVALUATION_CRITERIA[level]
        for cid, cls in classes_raw.items():
            if isinstance(cls, dict):
                merged["classes"][cid] = _normalize_class(cid, cls)
        if merged["active_class_id"] not in merged["classes"] and merged["classes"]:
            merged["active_class_id"] = next(iter(merged["classes"]))
        return merged

    if "video" in data:
        return _migrate_legacy_state(data)

    merged = deepcopy(DEFAULT_STATE)
    merged.update({k: v for k, v in data.items() if k in merged and k != "classes"})
    if isinstance(data.get("classes"), dict):
        for cid, cls in data["classes"].items():
            if isinstance(cls, dict):
                merged["classes"][cid] = _normalize_class(cid, cls)
    if merged["active_class_id"] not in merged["classes"] and merged["classes"]:
        merged["active_class_id"] = next(iter(merged["classes"]))
    return merged


def load_state() -> dict:
    _ensure_data_dir()
    with _lock:
        if not STATE_FILE.exists():
            return deepcopy(DEFAULT_STATE)
        try:
            with STATE_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return deepcopy(DEFAULT_STATE)

        needs_migration = isinstance(data, dict) and "video" in data and not (
            isinstance(data.get("classes"), dict) and data.get("classes")
        )
        normalized = _normalize_state(data)

    if needs_migration:
        # 旧形式 JSON を安全に新形式へ書き換え（初回読み込み時のみ）
        save_state(normalized)

    return normalized


def save_state(state: dict) -> dict:
    _ensure_data_dir()
    normalized = _normalize_state(state)
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized


def update_settings(**kwargs) -> dict:
    state = load_state()
    for key in ("display_language", "ai_model", "openai_api_key", "webshare_proxy_username", "webshare_proxy_password"):
        if key in kwargs:
            state[key] = kwargs[key]
    if "default_evaluation_criteria" in kwargs and isinstance(kwargs["default_evaluation_criteria"], dict):
        state["default_evaluation_criteria"] = _normalize_criteria(kwargs["default_evaluation_criteria"])
        for level in CEFR_LEVELS:
            if not state["default_evaluation_criteria"][level]:
                state["default_evaluation_criteria"][level] = DEFAULT_EVALUATION_CRITERIA[level]
    return save_state(state)


def list_classes() -> list[dict]:
    state = load_state()
    return [
        {"id": c["id"], "name": c["name"], "created_at": c.get("created_at", "")}
        for c in state.get("classes", {}).values()
    ]


def get_class(class_id: str) -> dict | None:
    state = load_state()
    return state.get("classes", {}).get(class_id)


def get_active_class_id() -> str:
    state = load_state()
    active = state.get("active_class_id") or ""
    if active and active in state.get("classes", {}):
        return active
    classes = state.get("classes") or {}
    if classes:
        return next(iter(classes))
    return ""


def set_active_class(class_id: str) -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")
    state["active_class_id"] = class_id
    return save_state(state)


def create_class(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("クラス名を入力してください。")
    state = load_state()
    class_id = _slug_id(name)
    while class_id in state["classes"]:
        class_id = _slug_id(name)
    state["classes"][class_id] = {
        "id": class_id,
        "name": name,
        "created_at": _now_iso(),
        "current": deepcopy(DEFAULT_CLASS_CURRENT),
        "archive": [],
    }
    state["active_class_id"] = class_id
    save_state(state)
    return state["classes"][class_id]


def update_class_current(class_id: str, current_data: dict) -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")
    state["classes"][class_id]["current"] = _normalize_current(
        {**state["classes"][class_id]["current"], **current_data}
    )
    save_state(state)
    return state["classes"][class_id]


def archive_class_current(class_id: str, title: str = "") -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")
    cls = state["classes"][class_id]
    current = cls.get("current") or deepcopy(DEFAULT_CLASS_CURRENT)
    if not (current.get("script") or "").strip() and not (current.get("video_id") or "").strip():
        raise ValueError("アーカイブする授業データがありません。URL またはスクリプトを設定してください。")

    archive_item = {
        "title": (title or "").strip() or (current.get("video_id") or "無題のアーカイブ"),
        "archived_at": _now_iso(),
        **deepcopy(current),
    }
    cls.setdefault("archive", []).insert(0, archive_item)
    update_submission_lesson_title(
        class_id,
        lesson_key(
            archive_item.get("video_id", ""),
            archive_item.get("start_seconds", 0),
            archive_item.get("end_seconds", 0),
        ),
        archive_item["title"],
    )
    cls["current"] = deepcopy(DEFAULT_CLASS_CURRENT)
    save_state(state)
    return cls


def reset_class_current(class_id: str) -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")

    cls = state["classes"][class_id]
    cls["current"] = deepcopy(DEFAULT_CLASS_CURRENT)
    save_state(state)
    return cls


def restore_class_archive(class_id: str, archive_index: int) -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")

    cls = state["classes"][class_id]
    archive = cls.get("archive") if isinstance(cls.get("archive"), list) else []
    if archive_index < 0 or archive_index >= len(archive):
        raise ValueError("指定されたアーカイブが見つかりません。")

    restored = deepcopy(archive[archive_index])
    restored.pop("title", None)
    restored.pop("archived_at", None)
    cls["current"] = _normalize_current(restored)
    save_state(state)
    return cls


def delete_class_archive(class_id: str, archive_index: int) -> dict:
    state = load_state()
    if class_id not in state.get("classes", {}):
        raise ValueError("指定されたクラスが見つかりません。")

    cls = state["classes"][class_id]
    archive = cls.get("archive") if isinstance(cls.get("archive"), list) else []
    if archive_index < 0 or archive_index >= len(archive):
        raise ValueError("指定されたアーカイブが見つかりません。")

    archive.pop(archive_index)
    cls["archive"] = archive
    save_state(state)
    return cls


def copy_class_archive(class_id: str, archive_index: int, target_class_id: str) -> tuple[dict, dict]:
    state = load_state()
    classes = state.get("classes", {})
    if class_id not in classes:
        raise ValueError("コピー元のクラスが見つかりません。")
    if target_class_id not in classes:
        raise ValueError("コピー先のクラスが見つかりません。")
    if class_id == target_class_id:
        raise ValueError("同じクラスにはコピーできません。")

    source_cls = classes[class_id]
    source_archive = source_cls.get("archive") if isinstance(source_cls.get("archive"), list) else []
    if archive_index < 0 or archive_index >= len(source_archive):
        raise ValueError("指定されたアーカイブが見つかりません。")

    archive_item = deepcopy(source_archive[archive_index])
    archive_item["archived_at"] = _now_iso()
    classes[target_class_id].setdefault("archive", []).insert(0, archive_item)
    save_state(state)
    return classes[class_id], classes[target_class_id]


def get_evaluation_rubric(class_id: str, level: str) -> str:
    """クラス固有 → 空ならアプリデフォルト。"""
    level = level.upper()
    if level not in CEFR_LEVELS:
        level = "B1"
    state = load_state()
    cls = state.get("classes", {}).get(class_id)
    if cls:
        custom = (cls.get("current") or {}).get("evaluation_criteria") or {}
        text = str(custom.get(level) or "").strip()
        if text:
            return text
    default = state.get("default_evaluation_criteria") or DEFAULT_EVALUATION_CRITERIA
    return str(default.get(level) or DEFAULT_EVALUATION_CRITERIA[level]).strip()


# ─────────────────────────────────────────────
# 名簿・提出データ
# ─────────────────────────────────────────────

def load_roster() -> dict:
    """{ class_id: [ {number, name}, ... ] }"""
    _ensure_data_dir()
    with _lock:
        if not ROSTER_FILE.exists():
            return {}
        try:
            with ROSTER_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return data if isinstance(data, dict) else {}


def save_roster(roster: dict) -> None:
    _ensure_data_dir()
    with _lock:
        with ROSTER_FILE.open("w", encoding="utf-8") as f:
            json.dump(roster, f, ensure_ascii=False, indent=2)


def import_roster_from_excel(class_id: str, file_bytes: bytes) -> list[dict]:
    """
    Excelの1列目=HRクラス、2列目=出席番号、3列目=名前 として読み込む（1行目はヘッダーとして無視）。
    返り値: [{hr_class, number, name}, ...]
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    students = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        hr_class = str(row[0]).strip() if row and row[0] is not None else ""
        number = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        name = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
        if hr_class or number or name:
            students.append({"hr_class": hr_class, "number": number, "name": name})
    roster = load_roster()
    roster[class_id] = students
    save_roster(roster)
    return students


def get_roster(class_id: str) -> list[dict]:
    """指定クラスの名簿を返す。未登録なら空リスト。"""
    roster = load_roster()
    students = roster.get(class_id, [])
    if not isinstance(students, list):
        return []
    normalized = []
    for student in students:
        if isinstance(student, dict):
            normalized.append(
                {
                    "hr_class": str(student.get("hr_class") or student.get("class_name") or "").strip(),
                    "number": str(student.get("number") or "").strip(),
                    "name": str(student.get("name") or "").strip(),
                }
            )
    return normalized


def load_submissions() -> list[dict]:
    """全提出データを返す。"""
    _ensure_data_dir()
    with _lock:
        if not SUBMISSIONS_FILE.exists():
            return []
        try:
            with SUBMISSIONS_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return data if isinstance(data, list) else []


def save_submission(
    class_id: str,
    class_name: str,
    student_hr_class: str,
    student_number: str,
    student_name: str,
    transcript: str,
    feedback: str,
    level: str,
    lesson_title: str = "",
    lesson_key_value: str = "",
    lesson_video_id: str = "",
    lesson_start_seconds: int = 0,
    lesson_end_seconds: int = 0,
) -> dict:
    """1件の提出データを追記保存して返す。"""
    _ensure_data_dir()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "submitted_at": _now_iso(),
        "class_id": class_id,
        "class_name": class_name,
        "student_hr_class": str(student_hr_class).strip(),
        "student_number": str(student_number).strip(),
        "student_name": str(student_name).strip(),
        "level": level,
        "lesson_title": str(lesson_title).strip(),
        "lesson_key": str(lesson_key_value).strip(),
        "lesson_video_id": str(lesson_video_id).strip(),
        "lesson_start_seconds": _coerce_nonnegative_int(lesson_start_seconds, 0),
        "lesson_end_seconds": _coerce_nonnegative_int(lesson_end_seconds, 0),
        "transcript": str(transcript).strip(),
        "feedback": str(feedback).strip(),
    }
    with _lock:
        submissions = []
        if SUBMISSIONS_FILE.exists():
            try:
                with SUBMISSIONS_FILE.open(encoding="utf-8") as f:
                    data = json.load(f)
                    submissions = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                submissions = []
        submissions.append(entry)
        with SUBMISSIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(submissions, f, ensure_ascii=False, indent=2)
    return entry


def update_submission_lesson_title(class_id: str, lesson_key_value: str, lesson_title: str) -> int:
    if not class_id or not lesson_key_value or not lesson_title:
        return 0
    _ensure_data_dir()
    updated = 0
    with _lock:
        submissions = []
        if SUBMISSIONS_FILE.exists():
            try:
                with SUBMISSIONS_FILE.open(encoding="utf-8") as f:
                    data = json.load(f)
                    submissions = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                submissions = []
        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            if submission.get("class_id") == class_id and submission.get("lesson_key") == lesson_key_value:
                if submission.get("lesson_title") != lesson_title:
                    submission["lesson_title"] = lesson_title
                    updated += 1
        if updated:
            with SUBMISSIONS_FILE.open("w", encoding="utf-8") as f:
                json.dump(submissions, f, ensure_ascii=False, indent=2)
    return updated


def score_only_feedback(feedback: str) -> str:
    text = str(feedback or "").strip()
    start = text.find("項目別評価点")
    if start < 0:
        return text
    rest = text[start:]
    match = re.search(
        r"\n\s*(要点チェックとキーワードチェック|文法・構成アドバイス|【AIからの模範要約】|今回の要約スピーチへのアドバイス|今回の要約スピーチ文の改良例)",
        rest,
    )
    if match:
        rest = rest[: match.start()]
    return rest.strip()


def extract_score_breakdown(feedback: str) -> dict:
    score_text = score_only_feedback(feedback)
    patterns = {
        "total_score": r"合計:\s*(\d+)\s*/\s*(\d+)",
        "content_score": r"内容理解・要点:\s*(\d+)\s*/\s*(\d+)",
        "organization_score": r"構成・流れ:\s*(\d+)\s*/\s*(\d+)",
        "language_score": r"英語表現:\s*(\d+)\s*/\s*(\d+)",
        "speaking_summary_score": r"即興スピーキング要約:\s*(\d+)\s*/\s*(\d+)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, score_text)
        result[key] = int(match.group(1)) if match else ""
    return result


def get_submissions(class_id: str | None = None) -> list[dict]:
    """class_id を指定するとそのクラスのみ、None なら全件返す。新しい順。"""
    submissions = load_submissions()
    if class_id:
        submissions = [s for s in submissions if s.get("class_id") == class_id]
    return list(reversed(submissions))


def delete_submission(submission_id: str) -> bool:
    """指定IDの提出データを削除。成功したら True。"""
    _ensure_data_dir()
    with _lock:
        submissions = []
        if SUBMISSIONS_FILE.exists():
            try:
                with SUBMISSIONS_FILE.open(encoding="utf-8") as f:
                    data = json.load(f)
                    submissions = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                submissions = []
        new_list = [s for s in submissions if s.get("id") != submission_id]
        if len(new_list) == len(submissions):
            return False
        with SUBMISSIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(new_list, f, ensure_ascii=False, indent=2)
    return True
