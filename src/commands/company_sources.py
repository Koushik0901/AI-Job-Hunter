from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from db import init_db, set_company_source_enabled
from services.company_source_service import import_companies, list_companies_table
from services.company_registry_service import probe_company_sources


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
        console = Console()
        result = probe_company_sources(args.slug, extra_slugs=[args.slug])
        matches = list(result.get("matches") or [])
        zero_job_matches = list(result.get("zero_job_matches") or [])
        if not matches:
            if zero_job_matches:
                console.print(
                    f"[yellow]No boards with active job listings found for '{args.slug}'.[/yellow]"
                )
                console.print(
                    f"[dim]{len(zero_job_matches)} hit(s) with 0 jobs were suppressed.[/dim]"
                )
            else:
                console.print(f"[yellow]No ATS board found for '{args.slug}'.[/yellow]")
            return

        table = Table(title=f"ATS boards found for '{args.slug}'", show_header=True)
        table.add_column("Slug", style="cyan")
        table.add_column("ATS", style="green")
        table.add_column("Jobs", justify="right")
        table.add_column("URL")
        for match in matches:
            table.add_row(
                str(match.get("slug") or ""),
                str(match.get("ats_type") or ""),
                str(int(match.get("jobs", 0) or 0)),
                str(match.get("ats_url") or ""),
            )
        console.print(table)
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
