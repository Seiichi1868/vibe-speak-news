import re

from openai import OpenAI

from services.openai_utils import create_json_chat_completion

# 総評末尾に付きやすい、内容と無関係な汎用励まし（後処理で除去）
_OPENING_FLUFF_RE = re.compile(
    r"(今日の(挑戦|要約)|今の一歩|よい土台|良い土台|"
    r"(いい|良い|よい)(ステップ|出発点|スタート)|"
    r"確かな一歩|続けて取り組)"
)

RUBRICS = {
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

LEVEL_GRAMMAR_ADVICE_GUIDANCE = {
    "A1": (
        "A1向け: 主語+動詞の短い文、基本語彙、1文1情報を優先する。"
        "難しい接続や言い換えより、誰が何をしたかを英語で言えるように助言する。"
    ),
    "A2": (
        "A2向け: 短い文を because, and, but でつなぎ、場所・理由・結果を1つずつ足す助言にする。"
        "基本時制や複数形など、要約を少し詳しくする表現を扱う。"
    ),
    "B1": (
        "B1向け: ニュース要約として、導入→主要事実→理由/影響→まとめの流れを作る助言にする。"
        "however, for example, as a result などの接続表現や、情報の優先順位づけを入れる。"
    ),
    "B2": (
        "B2向け: 事実の羅列ではなく、因果・対比・影響を論理的に結ぶ助言にする。"
        "パラフレーズ、抽象語、分詞構文/関係詞などを必要に応じて使い、ニュースの背景や含意まで整理する観点を入れる。"
    ),
}


LEVEL_SCORING_GUIDANCE = {
    "A1": (
        "A1はやや寛容に評価する。目安語数を満たし、中心内容・短い構成・基本語彙・即興要約としての伝わりやすさが"
        "それぞれの評価項目でおおむね満たされていれば、満点も積極的に出す。"
        "A1では高度な言い換えや複雑な接続表現がなくても減点しすぎない。"
    ),
    "A2": (
        "A2は、中心内容に加えて、場所・理由・結果などの補足情報が短い文で伝わるかを見る。"
        "基本接続語で情報を少し広げられていれば高く評価する。"
    ),
    "B1": (
        "B1は、複数の主要事実を整理し、流れと接続があるかを見る。"
        "事実の羅列だけでなく、理由や影響をある程度つなげていれば高く評価する。"
    ),
    "B2": (
        "B2は厳しめに評価する。語数を満たしていても、A1/A2のような単調な短文の羅列、"
        "同じ語句の反復、and中心の単純接続、言い換えや因果・対比・背景説明の不足が目立つ場合は、"
        "英語表現・構成・即興スピーキング要約を高くしすぎない。B2ではパラフレーズ、論理展開、情報の統合が必要。"
    ),
}


LEVEL_WORD_TARGETS = {
    "A1": 50,
    "A2": 70,
    "B1": 90,
    "B2": 110,
}

NO_RELEVANT_CONTENT_MESSAGE = "内容がない、もしくは関連のない内容のため出力できません"

# 本文（要点・文法）用 — 励まし多め
MODEL_COACH_STYLE = {
    "gpt-4o-mini": (
        "温かくシンプルに。伴走感を出し、"
        "褒めとアドバイスをバランスよく。"
    ),
    "gpt-5-mini": (
        "やさしく具体的に。「次はこうしてみましょう」と前向きに。"
    ),
    "gpt-5.4-mini": (
        "丁寧で的確。良い点と改善点を具体的に、レポート調は禁止。"
    ),
    "gpt-5.4-nano": (
        "短く要点だけ。無駄な形容は省き、励ましは1文程度に留める。"
    ),
}

# 冒頭総評（opening）専用 — 誉めすぎず、客観的なバランス
MODEL_OPENING_STYLE = {
    "gpt-4o-mini": (
        "総評は2〜3文でコンパクトに。できた点1つと、CEFR基準で伸びしろ1つを"
        "正直に述べる。過度な称賛（「完璧」「素晴らしい」連発）は禁止。"
    ),
    "gpt-5-mini": (
        "総評はCEFR {level} としての到達度を率直に評価する。"
        "良い点・足りない点をそれぞれ1つ、バランスよく。"
        "締めの汎用励まし文は書かない。"
    ),
    "gpt-5.4-mini": (
        "総評は分析的に。要約の強み1点と弱み1点を、"
        "事実に基づいて述べる。感情的な誉め言葉は控えめに。"
    ),
    "gpt-5.4-nano": (
        "総評は最短2文。到達した点と次に必要な点を事実ベースで。"
        "「えらい」「最高」などの大げさな褒めは使わない。"
    ),
}


def _coach_style_for_model(model: str) -> str:
    return MODEL_COACH_STYLE.get(model, MODEL_COACH_STYLE["gpt-4o-mini"])


def _opening_style_for_model(model: str, level: str) -> str:
    template = MODEL_OPENING_STYLE.get(model, MODEL_OPENING_STYLE["gpt-4o-mini"])
    return template.replace("{level}", level)


def _drop_redundant_anata(text: str) -> str:
    """毎文の「あなたは」「あなたの〜は」を除き、自然な直接語りかけにする。"""
    if not text:
        return text
    text = re.sub(r"あなたは[、,]?\s*", "", text)
    text = re.sub(r"あなたの", "", text)
    return text.strip()


def _promote_a1_mindset(text: str, level: str) -> str:
    if level.upper() != "A1" or not text:
        return text
    text = re.sub(r"【CEFR\s*A1\s*レベルでの評価】", "【基礎レベルでの評価】", text)
    text = text.replace("CEFR A1", "基礎レベル")
    text = text.replace("A1/A2", "基礎から次のレベル")
    text = re.sub(r"A1\s*レベル", "基礎レベル", text)
    text = re.sub(r"A1(らしく|として)[、,]?\s*", "", text)
    text = text.replace("基礎レベルとして", "次のA2につなげるために")
    text = text.replace("A1", "基礎レベル")
    return text.strip()


def _trim_opening_fluff(opening: str) -> str:
    """総評末尾の、根拠の薄い汎用励まし文を取り除く。"""
    lines = opening.split("\n")
    if not lines:
        return opening

    header_idx = 0
    if lines[0].startswith("【CEFR"):
        header_idx = 1
        while header_idx < len(lines) and not lines[header_idx].strip():
            header_idx += 1

    if header_idx >= len(lines):
        return opening

    body = "\n".join(lines[header_idx:]).strip()
    if not body:
        return opening

    parts = re.split(r"(?<=[。！？])", body)
    parts = [p for p in parts if p.strip()]
    while len(parts) > 1 and _OPENING_FLUFF_RE.search(parts[-1]):
        parts.pop()

    trimmed_body = "".join(parts).strip()
    if not trimmed_body:
        return opening

    header = "\n".join(lines[:header_idx]).rstrip()
    if header:
        return f"{header}\n{trimmed_body}" if trimmed_body else header
    return trimmed_body


def _count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", text or ""))


def _word_count_penalty(level: str, word_count: int) -> int:
    target = LEVEL_WORD_TARGETS.get(level.upper())
    if not target:
        return 0
    ratio = word_count / target
    if ratio <= 0.4:
        return 2
    if ratio < 0.7:
        return 1
    return 0


def _word_count_note(level: str, word_count: int) -> str:
    target = LEVEL_WORD_TARGETS.get(level.upper())
    if not target:
        return ""
    level_label = "基礎レベル" if level.upper() == "A1" else level.upper()
    return (
        f"語数は約{word_count}語で、{level_label}の目安（約{target}語）よりかなり少ないです。"
        "要約の内容が少ないために追加で減点されています。"
    )


def _remove_word_count_notes(comment: str) -> str:
    comment = re.sub(r"語数は約\d+語で、[A-Z0-9]+の目安（約\d+語）よりかなり少ないです。", "", comment)
    comment = re.sub(r"要約の内容が少ないために(評価が低くなっています|追加で減点されています)。", "", comment)
    comment = re.sub(r"(基準|目安)語数に対してやや短いです?。?", "", comment)
    comment = re.sub(r"(基準|目安)語数よりやや短いです?。?", "", comment)
    comment = re.sub(r"語数がやや短いです?。?", "", comment)
    return re.sub(r"\s+", " ", comment).strip()


def _meets_word_target(level: str, student_summary: str) -> bool:
    target = LEVEL_WORD_TARGETS.get(level.upper())
    return bool(target and _count_words(student_summary) >= target)


def _apply_word_count_adjustment(scores: dict, level: str, student_summary: str) -> dict:
    if not isinstance(scores, dict):
        return {}
    word_count = _count_words(student_summary)
    penalty = _word_count_penalty(level, word_count)
    if penalty <= 0:
        adjusted = dict(scores)
        for key in ("content", "organization", "language", "speaking_summary"):
            item = adjusted.get(key)
            if isinstance(item, dict):
                adjusted[key] = {**item, "comment": _remove_word_count_notes(str(item.get("comment") or ""))}
        return adjusted

    adjusted = dict(scores)
    note = _word_count_note(level, word_count)
    for key in ("content", "organization", "language", "speaking_summary"):
        item = adjusted.get(key)
        if not isinstance(item, dict):
            continue
        try:
            current_score = int(item.get("score", 0))
        except (TypeError, ValueError):
            current_score = 0
        comment = _remove_word_count_notes(str(item.get("comment") or "").strip())
        adjusted_score = 0 if current_score <= 0 else max(1, current_score - penalty)
        item = {**item, "score": adjusted_score}
        if note:
            item["comment"] = f"{comment} {note}".strip() if comment else note
        adjusted[key] = item

    return adjusted


_OFF_TOPIC_PATTERN = re.compile(
    r"(内容がない|関連がない|関係がない|無関係|かけ離れ|別の動画|別のトピック|指定された動画ではない)"
)


def _apply_off_topic_adjustment(scores: dict) -> dict:
    """Zero out organization and speaking_summary, cap language at 2, when content is off-topic."""
    if not isinstance(scores, dict):
        return scores
    content = scores.get("content") or {}
    try:
        content_score = int(content.get("score", 0))
    except (TypeError, ValueError):
        return scores
    comment = str(content.get("comment") or "")
    if content_score > 0 or not _OFF_TOPIC_PATTERN.search(comment):
        return scores
    adjusted = dict(scores)
    for key in ("organization", "speaking_summary"):
        item = adjusted.get(key)
        if isinstance(item, dict):
            adjusted[key] = {**item, "score": 0}
    lang = adjusted.get("language")
    if isinstance(lang, dict):
        try:
            lang_score = int(lang.get("score", 0))
        except (TypeError, ValueError):
            lang_score = 0
        adjusted["language"] = {**lang, "score": min(lang_score, 2)}
    return adjusted


def _score_text_from_data(data: dict, level: str, student_summary: str) -> str:
    if not isinstance(data, dict):
        return ""
    scores = _apply_word_count_adjustment(data.get("scores") or {}, level, student_summary)
    scores = _apply_off_topic_adjustment(scores)
    return _format_scores(scores, level)


def _has_no_relevant_content(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    content = (data.get("scores") or {}).get("content")
    if not isinstance(content, dict):
        return False
    try:
        score = int(content.get("score", 0))
    except (TypeError, ValueError):
        return False
    comment = str(content.get("comment") or "")
    return score <= 0 and re.search(r"(内容がない|関連がない|関係がない|無関係|かけ離れ)", comment)


def format_score_only_response(data: dict, level: str, student_summary: str) -> str:
    score_text = _score_text_from_data(data, level, student_summary)
    if score_text:
        return _promote_a1_mindset("\n".join(["項目別評価点", score_text]).strip(), level)
    return _promote_a1_mindset("項目別評価点\n評価点を生成できませんでした。", level)


def _format_scores(scores: dict, level: str = "") -> str:
    if not isinstance(scores, dict):
        return ""

    labels = (
        ("content", "内容理解・要点"),
        ("organization", "構成・流れ"),
        ("language", "英語表現"),
        ("speaking_summary", "即興スピーキング要約"),
    )
    lines = []
    total = 0
    total_max = 0
    for key, label in labels:
        item = scores.get(key)
        if not isinstance(item, dict):
            continue
        try:
            score = int(item.get("score", 0))
            max_score = int(item.get("max", 5) or 5)
        except (TypeError, ValueError):
            continue
        score = max(0, min(score, max_score))
        total += score
        total_max += max_score
        comment = _promote_a1_mindset(
            _drop_redundant_anata(str(item.get("comment") or "").strip()),
            level,
        )
        line = f"- {label}: {score}/{max_score}"
        if comment:
            line += f" — {comment}"
        lines.append(line)

    if not lines:
        return ""
    return "\n".join([f"合計: {total}/{total_max}", *lines])


def evaluation_system_prompt(level: str, model: str, rubric_override: str | None = None) -> str:
    rubric = (rubric_override or "").strip() or RUBRICS.get(level, RUBRICS["B1"])
    style = _coach_style_for_model(model)
    opening_style = _opening_style_for_model(model, level)
    grammar_guidance = LEVEL_GRAMMAR_ADVICE_GUIDANCE.get(level, LEVEL_GRAMMAR_ADVICE_GUIDANCE["B1"])
    scoring_guidance = LEVEL_SCORING_GUIDANCE.get(level, LEVEL_SCORING_GUIDANCE["B1"])
    return f"""あなたは高校生向けの英語教師です。ニュース要約に挑戦した生徒に、Vibe Speak（音読アプリ）のように、優しく直接語りかけてください。

【絶対ルール — 違反禁止】
- 生徒1人に直接語りかける（手紙のような二人称）。ただし主語の「あなたは」「あなたの〜は」は毎文入れない（日本語として不自然）
- 主語は省略し、述語や話題で伝える（例: 「主要な事実をおおむね押さえています」「接続詞を意識すると伝わります」）
- 「あなた」は全体で0〜1回まで。どうしても必要なときだけ使う
- 禁止: 「生徒は〜」「学習者は〜」など第三者・観察者の説明（「要約には〜」のように要約を主語にするのは可）
- 改善点は断定調で優しく。「〜してみましょう」「〜するともっと伝わります」
- 「〜可能性があります」など曖昧な表現は使わない
- 生徒の要約は Web Speech API による音声文字起こしを主に想定する。文頭の大文字化、句読点、ピリオド、カンマ、細かな capitalization は音声認識由来なので文法指摘にしない
- 現在の課題は即興スピーキング要約であり、ライティングの完成原稿ではない。自分の短い反応やつなぎ表現（例: “I also even like it”）を「消す」とは指導しない
- 個人的な反応が長くて要点を圧迫している場合だけ、「最初に短く反応してからニュースの事実に戻る」「次の文で内容説明を足す」のように、話し方として改善できる提案にする
- 文法アドバイスは、語順、時制、主語と動詞、冠詞、前置詞、語彙選択、文同士のつながりなど、発話内容として改善できる点に絞る
- 項目別評価点は各5点満点。CEFR {level} の到達目標に対して採点し、厳しすぎず甘すぎず、理由は短く具体的に書く
- CEFR {level} の採点方針: {scoring_guidance}
- 発話量による情報量の差を全4項目に反映する。目安語数は A1=50語、A2=70語、B1=90語、B2=110語
- 発話語数が目安の70%未満なら全4項目から追加で1点減点、40%以下なら全4項目から追加で2点減点する。ただし無回答・無関係でない限り最低1点は残す
- 語数不足で点を下げる場合は、「要約の内容が少ないために追加で減点されています。」のように、学習者に理由が分かる文を該当項目のコメントに入れる
- 目安語数を満たしていても、参照スクリプトの事実が少なければ内容理解点は上げすぎない。逆に多少短くても、重要事実が複数正確なら理由付きで評価する
- 生徒の提出内容が参照スクリプトとかけ離れている、関係がない、別の動画・別のトピックについて話している、または実質的な内容がない場合は、内容理解・要点・構成・流れ・即興スピーキング要約をすべて0/5にする。英語表現（language）のみ最高2/5まで評価してよい。その場合、content_check と model_summary_en は必ず「{NO_RELEVANT_CONTENT_MESSAGE}」だけにする。再受験時のヒントになる要点、キーワード、改良例、模範文は出さない。openingには「指定された動画ではなく別のトピックの内容が含まれているため、正確に評価できません」と明記する

【opening（総評）だけの特別ルール — 最重要】
- 誉めすぎ禁止。「完璧」「素晴らしい」「本当にえらい」などの過剰な称賛は使わない
- バランスの取れた客観的な総評にする（良い点1つ ＋ CEFR基準での伸びしろ1つ）。2〜3文で終える
- 総評の最後に、内容と無関係な汎用励まし・メタ談話を足さない（伸びしろの文で締める）
- 評価が高い場合（目安として合計17/20以上）は、総評で無理に改善点を書かない。良くできていることを伝え、「さらにレベルを上げていきましょう」のように上位レベルへの挑戦を促す
- A1では「A1として」「A1らしく」のように最低レベルへ留める言い方は禁止。特にA1で高評価の場合は、細かい改善点より「よくできています。次はA2に向けて理由や結果を少し足していきましょう」のように、次のレベルへ向かう前向きな総評にする
- 禁止の締め例: 「今日の挑戦はいいステップです」「今日の要約は良い出発点なので次も続けて〜」「今日はよい土台ができています」「今の一歩は良いスタートです」
- 「今日の〜」「一歩」「スタート」「出発点」「土台」「続けて取り組んで」など、要約の中身に触れない締め文は書かない
- 到達度を正直に伝えつつ、人格否定はしない
- {opening_style}

【要点・文法セクションの話し方】
{style}

【文法・構成アドバイスのCEFR別観点】
- grammar_advice は必ず CEFR {level} 向けに書く。全レベルで同じ一般論にしない
- {grammar_guidance}
- 上位レベルほど、単なる文法ミス指摘ではなく、CEFRで求められる構成力・情報整理・接続・言い換え・論理展開に踏み込む
- ただし発話が極端に短い場合は、レベル相応の助言に加えて、まず評価できる情報量を増やす必要があることを明確にする

【CEFR {level} の評価基準】
{rubric}

【良い例（opening）】
「【CEFR {level} レベルでの評価】
ニュースの主要な事実をおおむね押さえています。一方で、{level} レベルとしては接続詞や情報の順序にもう少し意識を入れると、説得力が増します。」

【A1で避ける表現】
「A1として」「A1らしく」「A1レベルとしては」で学習者を最低レベルに留める表現は禁止。A2以上へ進むための表現に言い換える

【悪い例（opening — 「あなた」主語の繰り返し）】
「あなたは主要な事実を押さえています。あなたの要約では接続詞が少ないです。」

【悪い例（opening — 締めの汎用励まし）】
「…説得力が増します。今日の挑戦はいいステップです。」
「…伸びしろがあります。今日の要約は良い出発点なので、次も続けて取り組んでみましょう。」

【悪い例（opening — 誉めすぎ）】
「本当にえらいです！完璧に近い要約です！あなたは最高です！」

【悪い例（第三者・レポート調）】
「生徒は主要なキーワードをいくつか含んでいる。構成面では改善の余地がある。」

出力は次の JSON オブジェクトのみ（キー名はそのまま）:
{{
  "opening": "【CEFR {level} レベルでの評価】で始まる総評2〜3文。良い点と伸びしろのみ。締めの汎用励ましは禁止",
  "scores": {{
    "content": {{"score": 0, "max": 5, "comment": "内容理解・要点把握について短く。発話量の目安（A1 50語/A2 70語/B1 90語/B2 110語）との差も反映"}},
    "organization": {{"score": 0, "max": 5, "comment": "話の順序・つながりについて短く。発話量が少なすぎる場合は評価材料不足も反映"}},
    "language": {{"score": 0, "max": 5, "comment": "語彙・文法・表現について短く。音声文字起こし由来の大文字/句読点は除外。語数が少なすぎる場合は評価できる語や文が少ないことも反映"}},
    "speaking_summary": {{"score": 0, "max": 5, "comment": "即興スピーキング要約としての伝わりやすさについて短く"}}
  }},
  "content_check": "要点チェックとキーワードチェックの本文のみ（見出しは書かない）。直接語りかけ。具体的に。「あなたは」不要。ただし提出内容が無関係・内容なしなら「内容がない、もしくは関連のない内容のため出力できません」のみ",
  "grammar_advice": "文法・構成アドバイスの本文のみ（見出しは書かない）。必ず CEFR {level} の到達目標に合わせ、A1/A2なら短く正確な文と基本接続、B1/B2なら構成・接続・言い換え・論理展開など上位レベルに必要な観点を入れる。即興スピーキング要約として評価し、個人的反応を単に消す指導はしない。音声文字起こしなので文頭大文字化・句読点不足は指摘しない。次の一歩。2〜4文。「あなたは」「あなたの」不要",
  "model_summary_en": "今回の要約スピーチ文の改良例。生徒の要約をもとに改善した英語1段落。ただし提出内容が無関係・内容なしなら「内容がない、もしくは関連のない内容のため出力できません」のみ"
}}"""


def evaluation_user_message(level: str, reference_script: str, student_summary: str) -> str:
    word_count = _count_words(student_summary)
    target = LEVEL_WORD_TARGETS.get(level.upper(), 0)
    target_status = "満たしています" if target and word_count >= target else "満たしていません"
    return f"""【参照スクリプト（動画の該当区間）】
{reference_script}

【あなた（生徒）が提出した要約】
{student_summary}

【語数情報（この数値を必ず使う）】
生徒の要約語数: 約{word_count}語
CEFR {level.upper()} の目安語数: 約{target}語
目安語数を{target_status}
目安語数を満たしている場合は、「基準語数に対して短い」「目安語数より短い」などとは書かないでください。

上記を踏まえ、JSON でフィードバックを書いてください。"""


def format_evaluation_response(data: dict, level: str, student_summary: str) -> str:
    opening = _drop_redundant_anata(
        _trim_opening_fluff(str(data.get("opening") or "").strip())
    )
    opening = _promote_a1_mindset(opening, level)
    content_check = _promote_a1_mindset(
        _drop_redundant_anata(str(data.get("content_check") or "").strip()),
        level,
    )
    grammar_advice = _promote_a1_mindset(
        _drop_redundant_anata(str(data.get("grammar_advice") or "").strip()),
        level,
    )
    model_summary_en = _promote_a1_mindset(str(data.get("model_summary_en") or "").strip(), level)
    score_text = _score_text_from_data(data, level, student_summary)
    if _has_no_relevant_content(data):
        content_check = NO_RELEVANT_CONTENT_MESSAGE
        model_summary_en = NO_RELEVANT_CONTENT_MESSAGE

    if not opening.startswith("【CEFR") and not opening.startswith("【基礎レベル"):
        opening = f"【CEFR 評価】\n{opening}"

    parts = [
        opening,
        "",
    ]
    if score_text:
        parts.extend(
            [
                "項目別評価点",
                score_text,
                "",
            ]
        )
    parts.extend(
        [
            "要点チェックとキーワードチェック",
            content_check,
            "",
            "文法・構成アドバイス",
            grammar_advice,
            "",
            "今回の要約スピーチ文の改良例",
            model_summary_en,
        ]
    )
    return _promote_a1_mindset("\n".join(parts).strip(), level)


def evaluate_summary(
    level: str,
    reference_script: str,
    student_summary: str,
    model: str,
    api_key: str,
    rubric_override: str | None = None,
) -> dict:
    if not api_key:
        raise ValueError(
            "OpenAI API キーが未設定です。"
            "管理画面（/admin/）の「OpenAI API キー」欄にキーを入力して保存してください。"
            "https://platform.openai.com/api-keys で取得できます。"
        )
    if not reference_script.strip():
        raise ValueError("参照スクリプトがありません。管理画面で動画・字幕を先に登録してください。")
    if not student_summary.strip():
        raise ValueError("要約テキストが空です。")

    client = OpenAI(api_key=api_key)
    data = create_json_chat_completion(
        client,
        model,
        [
            {"role": "system", "content": evaluation_system_prompt(level, model, rubric_override)},
            {"role": "user", "content": evaluation_user_message(level, reference_script, student_summary)},
        ],
        temperature=0.35,
    )
    return {
        "feedback": format_evaluation_response(data, level, student_summary),
        "score_feedback": format_score_only_response(data, level, student_summary),
    }
