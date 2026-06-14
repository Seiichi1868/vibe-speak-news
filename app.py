import os
from pathlib import Path
import threading
import webbrowser

from flask import Flask

from config import get_openai_api_key, load_environment
from routes.admin import admin_bp
from routes.main import main_bp

load_environment()


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "vibe-speak-news-dev-key")

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app


app = create_app()

AUTO_OPEN_MARKER = Path(".flask-browser-opened")


def _print_startup_banner(port: int) -> None:
    from services.network import get_lan_ip

    base = f"http://127.0.0.1:{port}"
    lan_ip = get_lan_ip()
    network_base = f"http://{lan_ip}:{port}" if lan_ip else ""
    print("\n" + "=" * 52)
    print("  Vibe Speak News — サーバー起動中")
    print("=" * 52)
    print(f"  生徒画面:  {base}/")
    print(f"  管理画面:  {base}/admin/")
    if network_base:
        print()
        print("  スマホ（同一 Wi‑Fi）:")
        print(f"  生徒画面:  {network_base}/")
        print(f"  管理画面:  {network_base}/admin/")
    if not get_openai_api_key():
        print()
        print("  ⚠ OpenAI API キー未設定")
        print(f"  → {base}/admin/ で「OpenAI API キー」を保存してください")
    print()
    print("  ※ このターミナルは閉じないでください（Ctrl+C で終了）")
    print(f"  ※ ポート {port} で起動中")
    print("=" * 52 + "\n")


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _schedule_browser_once(url: str) -> None:
    if AUTO_OPEN_MARKER.exists():
        return
    try:
        AUTO_OPEN_MARKER.write_text("opened\n", encoding="utf-8")
    except OSError:
        return
    threading.Timer(1.0, _open_browser, args=(url,)).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    url = f"http://127.0.0.1:{port}/"

    _print_startup_banner(port)

    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        try:
            AUTO_OPEN_MARKER.unlink()
        except FileNotFoundError:
            pass
    else:
        _schedule_browser_once(url)

    app.run(debug=True, host="0.0.0.0", port=port)
