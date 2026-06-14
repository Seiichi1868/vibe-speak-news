"""Gunicorn / Render 用 WSGI エントリポイント。"""
from app import create_app

application = create_app()
