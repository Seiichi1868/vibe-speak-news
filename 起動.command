#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "初回セットアップ中..."
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

source .venv/bin/activate
echo ""
echo "ブラウザが自動で開きます。開かない場合は http://127.0.0.1:5001/ を入力してください。"
echo ""
python app.py
