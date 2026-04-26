from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ai_job_hunter.db import init_db, set_company_source_enabled
from ai_job_hunter.services.company_source_service import import_companies, list_companies_table
from ai_job_hunter.services.company_registry_service import probe_company_sources


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

    p_imp = sub.add_parser("import", help="Import sources from GitHub lists or career-ops")
    p_imp.add_argument(
        "source",
        nargs="?",
        choices=["career-ops"],
        default=None,
        help="Specific source: 'career-ops'. Omit to run all GitHub list imports.",
    )
    p_imp.add_argument("--dry-run", action="store_true")

    p_disc = sub.add_parser("discover", help="Discover new sources via Brave Search API")
    p_disc.add_argument("--dry-run", action="store_true", dest="dry_run")

    p_all = sub.add_parser("check-all", help="Probe all configured sources and report coverage")
    p_all.add_argument(
        "--include-disabled",
        action="store_true",
        dest="include_disabled",
        help="Also probe disabled sources",
    )
    p_all.add_argument(
        "--ats",
        dest="ats_filter",
        metavar="NAME",
        help="Filter to one ATS provider (e.g. lever)",
    )


def _resolve_db(path_override: str | None):
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if turso_url:
        return turso_url, turso_token
    if path_override:
        return path_override, ""
    return str(Path.cwd() / "jobs.db"), ""


def run(args) -> None:
    if args.sources_cmd == "check-all":
        from collections import Counter

        from ai_job_hunter.db import list_company_sources as _list_sources
        from ai_job_hunter.services.probe_service import probe_company_sources_all
        from ai_job_hunter.services.scrape_service import safe_text

        db_url, db_token = _resolve_db(args.db)
        conn = init_db(db_url, db_token)
        all_rows = _list_sources(conn, enabled_only=False)
        conn.close()

        ats_filter = getattr(args, "ats_filter", None)
        include_disabled = getattr(args, "include_disabled", False)
        results = probe_company_sources_all(
            all_rows,
            include_disabled=include_disabled,
            ats_filter=ats_filter,
        )

        console = Console()
        if not results:
            console.print("[yellow]No sources matched the filter.[/yellow]")
            return

        table = Table(
            title=f"Source health check -- {len(results)} probed",
            show_header=True,
        )
        table.add_column("Company")
        table.add_column("ATS", style="cyan")
        table.add_column("Status")
        table.add_column("Jobs", justify="right")
        table.add_column("URL", style="dim", no_wrap=False)
        table.add_column("Note", style="dim")

        _STATUS_STYLE = {"OK": "bold green", "EMPTY": "yellow", "ERROR": "bold red"}
        for r in results:
            style = _STATUS_STYLE.get(r["probe_status"], "")
            jobs_str = str(r["probe_jobs"]) if r["probe_status"] in ("OK", "EMPTY") else "-"
            table.add_row(
                safe_text(r["name"]),
                r["ats_type"],
                f"[{style}]{r['probe_status']}[/{style}]",
                jobs_str,
                r.get("ats_url", ""),
                r.get("probe_note", ""),
            )
        console.print(table)
        console.print()

        by_ats: dict[str, list[dict]] = {}
        for r in results:
            by_ats.setdefault(r["ats_type"], []).append(r)

        for ats in sorted(by_ats):
            counts = Counter(r["probe_status"] for r in by_ats[ats])
            total = len(by_ats[ats])
            console.print(
                f"  [cyan]{ats:<14}[/cyan] "
                f"[green]{counts.get('OK', 0)} OK[/green]  .  "
                f"[yellow]{counts.get('EMPTY', 0)} empty[/yellow]  .  "
                f"[red]{counts.get('ERROR', 0)} errors[/red]  "
                f"of {total}"
            )
        return

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
        if getattr(args, "source", None) == "career-ops":
            from ai_job_hunter.services.company_source_service import import_career_ops
            import_career_ops(conn, dry_run=args.dry_run)
        else:
            import_companies(conn, dry_run=args.dry_run)
        conn.close()
        return

    if args.sources_cmd == "discover":
        from ai_job_hunter.services.company_source_service import run_discover
        run_discover(conn, dry_run=getattr(args, "dry_run", False))
        conn.close()
        return

    conn.close()
