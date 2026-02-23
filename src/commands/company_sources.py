from __future__ import annotations

import os

from rich.console import Console

from db import init_db, set_company_source_enabled
from services.company_source_service import import_companies, list_companies_table
from services.probe_service import check_company


def register(subparsers) -> None:
    parser = subparsers.add_parser("sources", help="Manage company source registry")
    parser.add_argument("--db", default=None, metavar="PATH", help="Local SQLite path (default: jobs.db). Ignored if TURSO_URL is set.")
    sub = parser.add_subparsers(dest="sources_cmd", required=True)

    sub.add_parser("list", help="List company sources")

    p_en = sub.add_parser("enable", help="Enable one source by id or slug")
    p_en.add_argument("target")

    p_dis = sub.add_parser("disable", help="Disable one source by id or slug")
    p_dis.add_argument("target")

    p_chk = sub.add_parser("check", help="Probe ATS boards for a slug")
    p_chk.add_argument("slug")

    p_imp = sub.add_parser("import", help="Import sources from GitHub lists")
    p_imp.add_argument("--dry-run", action="store_true")


def _resolve_db(path_override: str | None):
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        return turso_url, turso_token
    if path_override:
        return path_override, ""
    return str(Path.cwd() / "jobs.db"), ""


def run(args) -> None:
    if args.sources_cmd == "check":
        check_company(args.slug)
        return

    db_url, db_token = _resolve_db(args.db)
    conn = init_db(db_url, db_token)
    console = Console()

    if args.sources_cmd == "list":
        list_companies_table(conn)
        conn.close()
        return

    if args.sources_cmd == "enable":
        changed = set_company_source_enabled(conn, args.target, enabled=True)
        console.print(f"[green]Updated:[/green] enabled '{args.target}'" if changed else f"[yellow]No match for '{args.target}'.[/yellow]")
        conn.close()
        return

    if args.sources_cmd == "disable":
        changed = set_company_source_enabled(conn, args.target, enabled=False)
        console.print(f"[green]Updated:[/green] disabled '{args.target}'" if changed else f"[yellow]No match for '{args.target}'.[/yellow]")
        conn.close()
        return

    if args.sources_cmd == "import":
        import_companies(conn, dry_run=args.dry_run)
        conn.close()
        return

    conn.close()
