import io

import openpyxl
from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from config import AI_MODELS, CEFR_LEVELS, DISPLAY_LANGUAGES, get_openai_api_key, mask_api_key, save_openai_api_key
from services.cnn10 import fetch_cnn10_episodes
from services.cnn10_highlight import find_title_segment_in_transcript
from services.network import get_public_base_url
from services.storage import (
    DEFAULT_EVALUATION_CRITERIA,
    archive_class_current,
    copy_class_archive,
    current_lesson_identity,
    create_class,
    delete_class_archive,
    delete_submission,
    get_active_class_id,
    get_class,
    get_roster,
    get_submissions,
    import_roster_from_excel,
    list_classes,
    load_state,
    reset_class_current,
    restore_class_archive,
    extract_score_breakdown,
    lesson_key,
    lesson_title_display,
    score_only_feedback,
    set_active_class,
    update_class_current,
    update_settings,
)
from services.youtube import extract_video_id, fetch_youtube_title, parse_time_to_seconds, seconds_to_display

admin_bp = Blueprint("admin", __name__)


def _active_class_or_none():
    class_id = get_active_class_id()
    if not class_id:
        return None, None
    return class_id, get_class(class_id)


@admin_bp.route("/api/cnn10/episodes", methods=["GET"])
def cnn10_episodes():
    try:
        offset = int(request.args.get("offset") or 0)
        limit = int(request.args.get("limit") or 10)
        data = fetch_cnn10_episodes(offset=offset, limit=limit)
        return jsonify({"ok": True, **data})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@admin_bp.route("/api/youtube/highlight", methods=["POST"])
def youtube_highlight():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "").strip()
    snippets = data.get("snippets") or []
    if not title:
        return jsonify({"ok": False, "error": "タイトルが必要です。"}), 400
    if not isinstance(snippets, list) or not snippets:
        return jsonify({"ok": False, "error": "文字起こしデータが必要です。"}), 400

    api_key = get_openai_api_key()
    if not api_key:
        return jsonify(
            {
                "ok": True,
                "highlight": {
                    "ok": False,
                    "error": "OpenAI API キーが未設定です。管理画面の設定からキーを保存してください。",
                },
            }
        )

    state = load_state()
    model = str(state.get("ai_model") or "gpt-4o-mini")
    try:
        highlight = find_title_segment_in_transcript(
            title,
            snippets,
            model=model,
            api_key=api_key,
        )
    except ValueError as exc:
        highlight = {"ok": False, "error": str(exc)}
    except Exception as exc:
        highlight = {"ok": False, "error": f"区間推定に失敗しました: {exc}"}

    return jsonify({"ok": True, "highlight": highlight})


@admin_bp.route("/")
def admin_index():
    state = load_state()
    class_id, cls = _active_class_or_none()
    current = (cls or {}).get("current") or {}
    api_key_configured = bool(get_openai_api_key())
    classes = list_classes()

    return render_template(
        "admin.html",
        state=state,
        classes=classes,
        active_class_id=class_id,
        active_class=cls,
        current=current,
        cefr_levels=CEFR_LEVELS,
        display_languages=DISPLAY_LANGUAGES,
        ai_models=AI_MODELS,
        default_criteria=state.get("default_evaluation_criteria") or DEFAULT_EVALUATION_CRITERIA,
        start_time_display=seconds_to_display(int(current.get("start_seconds") or 0)),
        end_time_display=seconds_to_display(int(current.get("end_seconds") or 0)),
        api_key_configured=api_key_configured,
        api_key_masked=mask_api_key(state.get("openai_api_key") or get_openai_api_key()),
    )


@admin_bp.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    try:
        if str(data.get("admin_password") or "") != "2479":
            return jsonify({"ok": False, "error": "管理設定のパスワードが違います。"}), 403

        openai_api_key = str(data.get("openai_api_key", "")).strip()
        if not openai_api_key:
            openai_api_key = (load_state().get("openai_api_key") or "").strip()
            if not openai_api_key:
                openai_api_key = get_openai_api_key()

        default_criteria = data.get("default_evaluation_criteria")
        kwargs = {
            "display_language": str(data.get("display_language", "ja")),
            "ai_model": str(data.get("ai_model", "gpt-4o-mini")),
            "openai_api_key": openai_api_key,
        }
        if isinstance(default_criteria, dict):
            kwargs["default_evaluation_criteria"] = default_criteria

        state = update_settings(**kwargs)

        if openai_api_key:
            save_openai_api_key(openai_api_key)

        return jsonify(
            {
                "ok": True,
                "state": {**state, "openai_api_key": mask_api_key(state.get("openai_api_key", ""))},
                "api_key_configured": bool(openai_api_key),
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@admin_bp.route("/api/classes", methods=["GET"])
def api_list_classes():
    return jsonify({"ok": True, "classes": list_classes(), "active_class_id": get_active_class_id()})


@admin_bp.route("/api/classes", methods=["POST"])
def api_create_class():
    data = request.get_json(silent=True) or {}
    try:
        cls = create_class(str(data.get("name", "")).strip())
        return jsonify({"ok": True, "class": cls, "active_class_id": cls["id"]})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@admin_bp.route("/api/classes/select", methods=["POST"])
def api_select_class():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id", "")).strip()
    try:
        set_active_class(class_id)
        cls = get_class(class_id)
        return jsonify({"ok": True, "active_class_id": class_id, "class": cls})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@admin_bp.route("/api/class/lesson", methods=["POST"])
def api_save_lesson():
    """選択中クラスの動画・スクリプト・評価基準・タイマー設定を保存。"""
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    if not class_id:
        return jsonify({"ok": False, "error": "クラスを選択または作成してください。"}), 400

    url = (data.get("url") or "").strip()
    script = (data.get("script") or "").strip()
    if not script:
        return jsonify({"ok": False, "error": "文字起こし（スクリプト）を入力してください。"}), 400

    try:
        video_id = extract_video_id(url) if url else ""
        if not video_id:
            return jsonify({"ok": False, "error": "YouTube URL または動画 ID を入力してください。"}), 400

        start_sec = parse_time_to_seconds(data.get("start_time", ""))
        end_sec = parse_time_to_seconds(data.get("end_time", ""))
        if start_sec >= end_sec:
            return jsonify({"ok": False, "error": "終了時間は開始時間より後にしてください。"}), 400

        criteria = data.get("evaluation_criteria")
        if not isinstance(criteria, dict):
            criteria = {}

        prep_sec = max(0, int(data.get("prep_timer_seconds") or 0))
        record_sec = max(0, int(data.get("record_timer_seconds") or 60))
        timers_visible = bool(data.get("timers_visible", True))
        subtitles_enabled = bool(data.get("subtitles_enabled", False))

        cls = update_class_current(
            class_id,
            {
                "source_url": url,
                "video_id": video_id,
                "start_seconds": start_sec,
                "end_seconds": end_sec,
                "script": script,
                "evaluation_criteria": criteria,
                "prep_timer_seconds": prep_sec,
                "record_timer_seconds": record_sec,
                "timers_visible": timers_visible,
                "subtitles_enabled": subtitles_enabled,
            },
        )
        return jsonify(
            {
                "ok": True,
                "class": cls,
                "message": f"「{cls['name']}」の授業設定を保存しました（スクリプト {len(script)} 文字）。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"保存に失敗しました: {exc}"}), 500


@admin_bp.route("/api/class/archive", methods=["POST"])
def api_archive_lesson():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    try:
        title = str(data.get("title") or "").strip()
        if not title:
            current = (get_class(class_id) or {}).get("current") or {}
            title = fetch_youtube_title(current.get("source_url") or current.get("video_id") or "")
        cls = archive_class_current(class_id, title)
        return jsonify(
            {
                "ok": True,
                "class": cls,
                "message": f"「{cls['name']}」の授業をアーカイブしました。新しい動画を設定できます。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"アーカイブに失敗しました: {exc}"}), 500


@admin_bp.route("/api/class/lesson/reset", methods=["POST"])
def api_reset_lesson():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    try:
        cls = reset_class_current(class_id)
        return jsonify(
            {
                "ok": True,
                "class": cls,
                "message": "現在の授業設定をリセットしました。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"リセットに失敗しました: {exc}"}), 500


@admin_bp.route("/api/class/archive/restore", methods=["POST"])
def api_restore_archive_lesson():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    try:
        archive_index = int(data.get("archive_index", -1))
        cls = restore_class_archive(class_id, archive_index)
        return jsonify(
            {
                "ok": True,
                "class": cls,
                "message": f"「{cls['name']}」の設定画面にアーカイブを戻しました。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"復元に失敗しました: {exc}"}), 500


@admin_bp.route("/api/class/archive/delete", methods=["POST"])
def api_delete_archive_lesson():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    try:
        archive_index = int(data.get("archive_index", -1))
        cls = delete_class_archive(class_id, archive_index)
        return jsonify(
            {
                "ok": True,
                "class": cls,
                "message": "アーカイブを削除しました。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"削除に失敗しました: {exc}"}), 500


@admin_bp.route("/api/class/archive/copy", methods=["POST"])
def api_copy_archive_lesson():
    data = request.get_json(silent=True) or {}
    class_id = str(data.get("class_id") or get_active_class_id()).strip()
    target_class_id = str(data.get("target_class_id") or "").strip()
    try:
        archive_index = int(data.get("archive_index", -1))
        source_cls, target_cls = copy_class_archive(class_id, archive_index, target_class_id)
        return jsonify(
            {
                "ok": True,
                "class": source_cls,
                "target_class": target_cls,
                "message": f"「{target_cls['name']}」へアーカイブをコピーしました。",
            }
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"コピーに失敗しました: {exc}"}), 500


@admin_bp.route("/api/share-link", methods=["GET"])
def share_link():
    level = (request.args.get("level") or "B1").upper()
    class_id = (request.args.get("class_id") or get_active_class_id()).strip()
    if level not in CEFR_LEVELS:
        return jsonify({"ok": False, "error": f"CEFR レベルは {', '.join(CEFR_LEVELS)} のいずれかです。"}), 400
    if not class_id:
        return jsonify({"ok": False, "error": "クラスを選択してください。"}), 400

    base = get_public_base_url(request)
    link = f"{base}/?class={class_id}&level={level}"
    return jsonify({"ok": True, "link": link, "level": level, "class_id": class_id})


# ── 名簿アップロード ──────────────────────────────────────────

@admin_bp.route("/api/roster/upload", methods=["POST"])
def upload_roster():
    class_id = request.form.get("class_id", "").strip()
    if not class_id:
        return jsonify({"ok": False, "error": "class_id が必要です。"}), 400
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "ファイルが選択されていません。"}), 400
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"ok": False, "error": ".xlsx または .xls ファイルを選択してください。"}), 400
    try:
        students = import_roster_from_excel(class_id, file.read())
        return jsonify({"ok": True, "students": students, "count": len(students)})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"読み込みエラー: {exc}"}), 500


@admin_bp.route("/api/roster/<class_id>", methods=["GET"])
def get_roster_api(class_id):
    return jsonify({"ok": True, "students": get_roster(class_id)})


# ── 提出結果一覧 ──────────────────────────────────────────────

def _lesson_options_for_class(class_id: str) -> list[dict]:
    cls = get_class(class_id)
    if not cls:
        return []
    options = []
    seen = set()

    for item in cls.get("archive") or []:
        key = lesson_key(item.get("video_id", ""), item.get("start_seconds", 0), item.get("end_seconds", 0))
        if key and key not in seen:
            options.append(
                {
                    "key": key,
                    "title": lesson_title_display(item.get("title", ""), item.get("video_id", ""), "無題のアーカイブ"),
                }
            )
            seen.add(key)

    current = current_lesson_identity(cls)
    if current["lesson_video_id"] and current["lesson_key"]:
        title = current["lesson_title"] or "現在の授業"
        if current["lesson_key"] not in seen:
            options.insert(0, {"key": current["lesson_key"], "title": title})
            seen.add(current["lesson_key"])
    return options


def _submission_with_lesson_display(submission: dict) -> dict:
    cls = get_class(submission.get("class_id", ""))
    submission_key = submission.get("lesson_key") or ""
    lesson_title = ""

    if cls and submission_key:
        for item in cls.get("archive") or []:
            key = lesson_key(item.get("video_id", ""), item.get("start_seconds", 0), item.get("end_seconds", 0))
            if key == submission_key:
                lesson_title = lesson_title_display(item.get("title", ""), item.get("video_id", ""), "無題のアーカイブ")
                break
        if not lesson_title:
            current = current_lesson_identity(cls)
            if current["lesson_key"] == submission_key:
                lesson_title = current["lesson_title"]

    if not lesson_title:
        lesson_title = lesson_title_display(
            submission.get("lesson_title", ""),
            submission.get("lesson_video_id", ""),
            "未分類",
        )
    return {**submission, "lesson_title": lesson_title}


@admin_bp.route("/api/class/lessons", methods=["GET"])
def list_class_lessons():
    class_id = request.args.get("class_id") or ""
    if not class_id:
        return jsonify({"ok": True, "lessons": []})
    return jsonify({"ok": True, "lessons": _lesson_options_for_class(class_id)})


@admin_bp.route("/api/submissions", methods=["GET"])
def list_submissions():
    class_id = request.args.get("class_id") or None
    lesson_key_filter = request.args.get("lesson_key") or None
    submissions = []
    for submission in get_submissions(class_id):
        submission = _submission_with_lesson_display(submission)
        if lesson_key_filter and submission.get("lesson_key") != lesson_key_filter:
            continue
        scores = extract_score_breakdown(submission.get("feedback", ""))
        submissions.append(
            {
                **submission,
                **scores,
                "feedback": score_only_feedback(submission.get("feedback", "")),
            }
        )
    return jsonify({"ok": True, "submissions": submissions})


@admin_bp.route("/api/submissions/<submission_id>", methods=["DELETE"])
def delete_submission_api(submission_id):
    ok = delete_submission(submission_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "データが見つかりません。"}), 404


@admin_bp.route("/api/submissions/export", methods=["GET"])
def export_submissions():
    """提出結果を Excel でダウンロード。?class_id=xxx で絞り込み可。"""
    class_id = request.args.get("class_id") or None
    lesson_key_filter = request.args.get("lesson_key") or None
    submissions = get_submissions(class_id)
    submissions = [_submission_with_lesson_display(s) for s in submissions]
    if lesson_key_filter:
        submissions = [s for s in submissions if s.get("lesson_key") == lesson_key_filter]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "提出結果"
    headers = [
        "提出日時",
        "授業クラス",
        "HRクラス",
        "出席番号",
        "名前",
        "動画タイトル",
        "内容理解",
        "構成",
        "英語表現",
        "即興要約",
        "合計",
        "レベル",
        "文字起こし",
        "AIフィードバック",
    ]
    ws.append(headers)

    for submission in submissions:
        scores = extract_score_breakdown(submission.get("feedback", ""))
        ws.append(
            [
                submission.get("submitted_at", ""),
                submission.get("class_name", ""),
                submission.get("student_hr_class", ""),
                submission.get("student_number", ""),
                submission.get("student_name", ""),
                submission.get("lesson_title", "") or "未分類",
                scores.get("content_score", ""),
                scores.get("organization_score", ""),
                scores.get("language_score", ""),
                scores.get("speaking_summary_score", ""),
                scores.get("total_score", ""),
                submission.get("level", ""),
                submission.get("transcript", ""),
                score_only_feedback(submission.get("feedback", "")),
            ]
        )

    col_widths = [20, 15, 12, 8, 12, 24, 8, 8, 10, 10, 8, 8, 60, 80]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"submissions_{class_id or 'all'}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
