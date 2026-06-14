"""ローカルネットワーク上のアクセス URL 生成。"""

import os
import socket

from flask import Request


def get_lan_ip() -> str:
    """同一 Wi‑Fi 内の端末からアクセスできる IPv4 アドレスを推定する。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def get_server_port(request: Request) -> int:
    host = str(request.host or "")
    if ":" in host:
        try:
            return int(host.rsplit(":", 1)[1])
        except ValueError:
            pass
    return int(os.environ.get("PORT", 5001))


def build_access_urls(request: Request) -> dict:
    port = get_server_port(request)
    lan_ip = get_lan_ip()
    local_base = f"http://127.0.0.1:{port}"
    network_base = f"http://{lan_ip}:{port}" if lan_ip else local_base

    return {
        "port": port,
        "lan_ip": lan_ip,
        "local_base": local_base,
        "network_base": network_base,
        "student_url": f"{network_base}/",
        "admin_url": f"{network_base}/admin/",
    }


def get_public_base_url(request: Request) -> str:
    """共有リンク等に使うベース URL。localhost 閲覧時は LAN IP を優先する。"""
    urls = build_access_urls(request)
    host = (request.host or "").split(":")[0]
    if urls["lan_ip"] and host in ("127.0.0.1", "localhost"):
        return urls["network_base"]
    return request.url_root.rstrip("/")
