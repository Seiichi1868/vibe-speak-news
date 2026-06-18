import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# Render 本番では render.yaml の disk.mountPath と同じパスを指す（未指定時は ./data）
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data"))).expanduser()
STATE_FILE = DATA_DIR / "app_state.json"
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"


def ensure_env_file() -> None:
    """初回起動時に .env.example から .env を生成。"""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")


def load_environment() -> None:
    ensure_env_file()
    load_dotenv(ENV_FILE, override=False)


load_environment()

DEFAULT_AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

CEFR_LEVELS = ("A1", "A2", "B1", "B2")
DISPLAY_LANGUAGES = ("ja", "en")
AI_MODELS = (
    "gpt-4o-mini",
    "gpt-5-mini",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
)


def get_openai_api_key() -> str:
    """環境変数 → 管理画面で保存したキーの順で取得。"""
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if key and not key.startswith("sk-your-"):
        return key

    try:
        from services.storage import load_state

        stored = (load_state().get("openai_api_key") or "").strip()
        if stored:
            return stored
    except Exception:
        pass

    return ""


def save_openai_api_key(key: str) -> None:
    """管理画面から保存したキーを .env にも書き込む。"""
    key = key.strip()
    lines: list[str] = []
    found = False

    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    for line in lines:
        if line.startswith("OPENAI_API_KEY="):
            if key:
                new_lines.append(f"OPENAI_API_KEY={key}")
            found = True
        else:
            new_lines.append(line)

    if key and not found:
        new_lines.append(f"OPENAI_API_KEY={key}")

    if not new_lines and key:
        new_lines = [f"OPENAI_API_KEY={key}"]

    ENV_FILE.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    os.environ["OPENAI_API_KEY"] = key


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    return key[:7] + "…" + key[-4:]
