from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from ai_job_hunter.db import init_db
from ai_job_hunter.dashboard.backend import repository
from ai_job_hunter.notify import notify_daily_briefing, telegram_message_hash


def register(subparsers) -> None:
    parser = subparsers.add_parser("daily-briefing", help="Generate and optionally send today's daily briefing")
    parser.add_argument("--db", default=None, metavar="PATH", help="Local SQLite path (default: jobs.db). Ignored if TURSO_URL is set.")
    parser.add_argument("--refresh-only", action="store_true", help="Refresh today's briefing without sending Telegram.")
    parser.add_argument("--send-now", action="store_true", help="Send today's briefing immediately if it has not already been sent.")


def _resolve_db() -> tuple[str, str, str]:
    turso_url = (os.getenv("TURSO_URL") or "").strip()
    turso_token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
    if turso_url:
        return turso_url, turso_token, "Turso"
    local_path = str(Path.cwd() / "jobs.db")
    return local_path, "", local_path


def run(args) -> None:
    db_url, db_auth_token, db_label = _resolve_db()
    if args.db and not (os.getenv("TURSO_URL") or "").strip():
        db_url = args.db
        db_label = args.db

    conn = init_db(db_url, db_auth_token)
    console = Console(stderr=True)
    try:
        briefing = repository.refresh_daily_briefing(conn, trigger_source="scheduled")
        console.print(f"[bold]Daily briefing refreshed[/bold] for {briefing['brief_date']} in {db_label}")

        should_send = bool(args.send_now or not args.refresh_only)
        if not should_send:
            return

        if briefing.get("telegram_sent_at"):
            console.print("[dim]Today's daily briefing was already sent; skipping Telegram.[/dim]")
            return

        token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
        chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        if not token or not chat_id:
            console.print("[dim]Telegram not configured - set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID[/dim]")
            return

        chunks = notify_daily_briefing(briefing, token, chat_id, console)
        updated = repository.mark_daily_briefing_sent(
            conn,
            brief_date=str(briefing.get("brief_date") or ""),
            message_hash=telegram_message_hash(chunks),
        )
        if updated and updated.get("telegram_sent_at"):
            console.print(f"[green]Daily briefing sent[/green] at {updated['telegram_sent_at']}")
    finally:
        conn.close()
