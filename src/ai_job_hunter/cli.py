from __future__ import annotations

import argparse
from pathlib import Path

from ai_job_hunter.notify import _load_dotenv
from ai_job_hunter.commands import company_sources, daily_briefing, scrape_jobs


def main() -> None:
    _load_dotenv(Path.cwd() / ".env")

    parser = argparse.ArgumentParser(description="AI Job Hunter CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    scrape_jobs.register(sub)
    company_sources.register(sub)
    daily_briefing.register(sub)

    args = parser.parse_args()
    if args.command == "scrape":
        scrape_jobs.run(args)
        return
    if args.command == "sources":
        company_sources.run(args)
        return
    if args.command == "daily-briefing":
        daily_briefing.run(args)
        return


if __name__ == "__main__":
    main()
