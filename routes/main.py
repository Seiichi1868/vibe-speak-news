from flask import Blueprint, jsonify, render_template, request

from config import CEFR_LEVELS, get_openai_api_key
from services.openai_eval import evaluate_summary
from services.storage import (
    current_lesson_identity,
    get_active_class_id,
    get_class,
    get_evaluation_rubric,
    list_classes,
    load_state,
    save_submission,
)
from services.youtube import build_youtube_embed_url

main_bp = Blueprint("main", __name__)


@main_bp.route("/health")
def health():
    return jsonify({"ok": True})


def _class_public_payload(class_id: str, origin: str) -> dict | None:
    cls = get_class(class_id)
    if not cls:
        return None
    current = cls.get("current") or {}
    video_id = (current.get("video_id") or "").strip()
    start_sec = int(current.get("start_seconds") or 0)
    end_sec = int(current.get("end_seconds") or 0)
    subtitles_enabled = bool(current.get("subtitles_enabled", False))
    embed_url = (
        build_youtube_embed_url(
            video_id,
            start_sec,
            end_sec,
            origin=origin,
            subtitles_enabled=subtitles_enabled,
        )
        if video_id
        else ""
    )

    return {
        "id": cls["id"],
        "name": cls["name"],
        "video": {
            "video_id": video_id,
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "embed_url": embed_url,
            "watch_url": f"https://www.youtube.com/watch?v={video_id}&t={start_sec}s" if video_id else "",
            "has_script": bool((current.get("script") or "").strip()),
            "subtitles_enabled": subtitles_enabled,
        },
        "timers": {
            "prep_seconds": int(current.get("prep_timer_seconds") or 0),
            "record_seconds": int(current.get("record_timer_seconds") or 60),
            "visible": bool(current.get("timers_visible", True)),
        },
    }


@main_bp.route("/")
def index():
    state = load_state()
    level = (request.args.get("level") or "B1").upper()
    if level not in CEFR_LEVELS:
        level = "B1"
    class_id = (request.args.get("class") or get_active_class_id()).strip()
    classes = list_classes()

    return render_template(
        "index.html",
        state=state,
        cefr_levels=CEFR_LEVELS,
        initial_level=level,
        initial_class_id=class_id,
        classes=classes,
        page_origin=request.host_url.rstrip("/"),
    )


@main_bp.route("/api/classes", methods=["GET"])
def api_classes():
    return jsonify({"ok": True, "classes": list_classes()})


@main_bp.route("/api/config")
def public_config():
    class_id = (request.args.get("class_id") or "").strip()
    if not class_id:
        return jsonify({"ok": False, "error": "クラス ID が必要です。"}), 400

    origin = request.host_url.rstrip("/")
    payload = _class_public_payload(class_id, origin)
    if not payload:
        return jsonify({"ok": False, "error": "クラスが見つかりません。"}), 404

    state = load_state()
    return jsonify(
        {
            "ok": True,
            "display_language": state.get("display_language", "ja"),
            "page_origin": origin,
            "class": payload,
        }
    )


@main_bp.route("/api/evaluate", methods=["POST"])
def evaluate():
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "B1").upper()
    summary = (data.get("summary") or "").strip()
    class_id = (data.get("class_id") or "").strip()
    student_hr_class = str(data.get("student_hr_class") or "").strip()
    student_number = str(data.get("student_number") or "").strip()
    student_name = str(data.get("student_name") or "").strip()

    if level not in CEFR_LEVELS:
        return jsonify({"ok": False, "error": f"CEFR レベルは {', '.join(CEFR_LEVELS)} のいずれかです。"}), 400
    if not class_id:
        return jsonify({"ok": False, "error": "クラスを選択してください。"}), 400

    cls = get_class(class_id)
    if not cls:
        return jsonify({"ok": False, "error": "クラスが見つかりません。"}), 404

    reference_script = (cls.get("current") or {}).get("script") or ""
    if not reference_script.strip():
        return jsonify(
            {"ok": False, "error": "このクラスには参照スクリプトが未設定です。管理画面で設定してください。"},
        ), 400

    state = load_state()
    model = state.get("ai_model") or "gpt-4o-mini"
    api_key = get_openai_api_key()
    rubric = get_evaluation_rubric(class_id, level)

    try:
        evaluation = evaluate_summary(
            level, reference_script, summary, model, api_key, rubric_override=rubric
        )
        feedback = evaluation["feedback"]
        score_feedback = evaluation["score_feedback"]
        if student_number or student_name:
            lesson = current_lesson_identity(cls)
            save_submission(
                class_id=class_id,
                class_name=cls.get("name") or class_id,
                student_hr_class=student_hr_class,
                student_number=student_number,
                student_name=student_name,
                transcript=summary,
                feedback=score_feedback,
                level=level,
                lesson_title=lesson["lesson_title"],
                lesson_key_value=lesson["lesson_key"],
                lesson_video_id=lesson["lesson_video_id"],
                lesson_start_seconds=lesson["lesson_start_seconds"],
                lesson_end_seconds=lesson["lesson_end_seconds"],
            )
        return jsonify({"ok": True, "feedback": feedback, "level": level, "class_id": class_id})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"評価に失敗しました: {exc}"}), 500
