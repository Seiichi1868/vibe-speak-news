# Vibe Speak News

> **本番は統合プラットフォーム [`vibes-apps`](../vibes-apps/) の `news_app/`（https://vibes-app-auz1.onrender.com/news/）を使用します。**  
> 本リポジトリはレガシー単体版です。新規開発は `vibes-apps` で行ってください。

動画要約・スピーチ評価アプリのプロトタイプ（Flask + Tailwind CSS）。

## 機能

- **管理画面** (`/admin`): クラスコード、表示言語、AI モデル設定、CEFR 付き共有リンク、YouTube 字幕の区間抽出
- **生徒画面** (`/`): Glassmorphism UI、YouTube 埋め込み（start/end）、準備・録音タイマー、Web Speech API 文字起こし、OpenAI による CEFR 別要約評価

## セットアップ

```bash
cd "Vibe Speak News"
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env に OPENAI_API_KEY を設定
python app.py
```

### いちばん簡単な起動（macOS）

Finder で **`起動.command`** をダブルクリック → ブラウザが自動で開きます。

### ターミナルから起動

```bash
cd "/Users/user/Desktop/Vibe Coding/Vibe Speak News"
source .venv/bin/activate
python app.py
```

**重要:** ターミナルに `Running on http://127.0.0.1:5001` と出ている間は、そのターミナルを閉じないでください。別タブでブラウザを開きます。

| 画面 | URL |
|------|-----|
| 生徒 | http://127.0.0.1:5001/ |
| 管理 | http://127.0.0.1:5001/admin/ |

`http://127.0.0.1:5000` では開きません（macOS が 5000 を占有しているため、**5001** を使います）。

※ macOS ではポート 5000 が AirPlay Receiver に使われるため、デフォルトは **5001** です。別ポートで起動する場合: `PORT=8080 python app.py`

## 使い方

1. 管理画面で YouTube URL と開始・終了時間を入力し「取得」で字幕を登録
2. 共有リンク（A2/B1/B2）を生徒に配布
3. 生徒画面で動画を視聴 → 準備 1 分 → 録音 1 分で要約 →「要約を AI に提出」

## 技術構成

```
app.py
config.py
routes/
  main.py      # 生徒画面・評価 API
  admin.py     # 管理画面・設定・YouTube API
services/
  storage.py   # JSON 永続化
  youtube.py   # 字幕抽出
  openai_eval.py
templates/
static/js/
```

## 注意

- Web Speech API は Chrome / Edge などでの利用を推奨
- YouTube 字幕は動画側で有効なものが必要です（手動・自動生成の英語字幕を順に試行）
- 自動取得に失敗した場合は管理画面の手動入力欄からスクリプトを保存できます
- 本番運用時は `FLASK_SECRET_KEY` を必ず変更してください
