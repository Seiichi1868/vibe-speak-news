"""YouTube 文字起こし取得用プロキシ設定（クラウド IP ブロック回避）。"""

from __future__ import annotations

import os


def _state_proxy_credentials() -> tuple[str, str]:
    try:
        from services.storage import load_state

        state = load_state()
        username = str(state.get("webshare_proxy_username") or "").strip()
        password = str(state.get("webshare_proxy_password") or "").strip()
        return username, password
    except Exception:
        return "", ""


def get_transcript_proxy_config():
    """環境変数 → 管理画面保存値の順でプロキシ設定を返す。"""
    from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

    ws_user = (os.environ.get("WEBSHARE_PROXY_USERNAME") or "").strip()
    ws_pass = (os.environ.get("WEBSHARE_PROXY_PASSWORD") or "").strip()
    if not ws_user or not ws_pass:
        stored_user, stored_pass = _state_proxy_credentials()
        ws_user = ws_user or stored_user
        ws_pass = ws_pass or stored_pass

    if ws_user and ws_pass:
        locations_raw = (os.environ.get("WEBSHARE_PROXY_LOCATIONS") or "").strip()
        locations = [part.strip() for part in locations_raw.split(",") if part.strip()] or None
        return WebshareProxyConfig(
            proxy_username=ws_user,
            proxy_password=ws_pass,
            filter_ip_locations=locations,
        )

    proxy_url = (
        (os.environ.get("YOUTUBE_PROXY_URL") or "").strip()
        or (os.environ.get("HTTPS_PROXY") or "").strip()
        or (os.environ.get("HTTP_PROXY") or "").strip()
    )
    if proxy_url:
        return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)

    return None


def transcript_proxy_configured() -> bool:
    return get_transcript_proxy_config() is not None


def create_youtube_transcript_api():
    from youtube_transcript_api import YouTubeTranscriptApi

    proxy_config = get_transcript_proxy_config()
    if proxy_config is None:
        return YouTubeTranscriptApi()
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def cloud_transcript_error_message() -> str:
    return (
        "YouTube がクラウドサーバー（Render 等）からの文字起こし取得をブロックしています。\n"
        "管理設定の「YouTube 文字起こし用プロキシ（Webshare）」に Residential プランの "
        "Proxy Username / Password を入力して保存してください。\n"
        "または Render の環境変数 WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD を設定してください。"
    )
