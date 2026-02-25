from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from db import init_db, prune_not_applied_older_than_days, set_application_status


def register(subparsers) -> None:
    parser = subparsers.add_parser("lifecycle", help="Manage job lifecycle status and retention")
    parser.add_argument("--db", default=None, metavar="PATH", help="Local SQLite path (default: jobs.db). Ignored if TURSO_URL is set.")
    sub = parser.add_subparsers(dest="lifecycle_cmd", required=True)

    p_stat = sub.add_parser("set-status", help="Set application status for one job URL")
    p_stat.add_argument("--url", required=True)
    p_stat.add_argument(
        "--status",
        required=True,
        choices=["not_applied", "staging", "applied", "interviewing", "offer", "rejected"],
    )

    p_prune = sub.add_parser("prune", help="Prune old not-applied jobs")
    p_prune.add_argument("--days", type=int, default=28)
    p_prune.add_argument("--apply", action="store_true", help="Actually delete rows (default is dry-run)")


def _resolve_db(path_override: str | None):
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        return turso_url, turso_token
    if path_override:
        return path_override, ""
    return str(Path.cwd() / "jobs.db"), ""


def run(args) -> None:
    db_url, db_token = _resolve_db(args.db)
    conn = init_db(db_url, db_token)
    console = Console()

    if args.lifecycle_cmd == "set-status":
        changed = set_application_status(conn, args.url, args.status)
        console.print(f"[green]Updated[/green] {args.url} -> {args.status}" if changed else f"[yellow]No job matched URL:[/yellow] {args.url}")
        conn.close()
        return

    if args.lifecycle_cmd == "prune":
        if args.apply:
            deleted = prune_not_applied_older_than_days(conn, args.days, dry_run=False)
            console.print(f"[green]Deleted {deleted} job(s).[/green]")
        else:
            would_delete = prune_not_applied_older_than_days(conn, args.days, dry_run=True)
            console.print(f"[yellow]Dry-run:[/yellow] would delete {would_delete} job(s). Use --apply to execute.")
        conn.close()
        return
