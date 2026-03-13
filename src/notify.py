"""
notify.py — .env loader, country bucketing, and Telegram notification helpers.
"""
from __future__ import annotations

import html
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_COUNTRY_ORDER = ["Canada", "USA / Remote", "Other"]
_COUNTRY_EMOJI = {"Canada": "\U0001f1e8\U0001f1e6", "USA / Remote": "\U0001f310", "Other": "\U0001f30d"}


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (values not overwritten)."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def bucket_country(location: str) -> str:
    """Classify a free-text location string into 'Canada', 'USA / Remote', or 'Other'."""
    loc = location.lower()
    canada_signals = (
        "canada",
        ", on", ", bc", ", ab", ", qc", ", mb", ", sk", ", ns", ", nb", ", nl", ", pe",
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
        "waterloo", "winnipeg", "halifax", "edmonton", "kitchener",
    )
    if any(sig in loc for sig in canada_signals):
        return "Canada"
    if not location.strip():
        return "USA / Remote"
    if any(sig in loc for sig in ("remote", "anywhere", "united states", "usa", "us only")):
        return "USA / Remote"
    return "Other"


def _escape_text(value: Any) -> str:
    return html.escape(str(value or ""))


def _escape_url(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _chunk_telegram_lines(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for line in lines:
        segment = line + "\n"
        if current_len + len(segment) > 4096 and current_parts:
            chunks.append("".join(current_parts).rstrip())
            current_parts = []
            current_len = 0
        current_parts.append(segment)
        current_len += len(segment)
    if current_parts:
        chunks.append("".join(current_parts).rstrip())
    return chunks


def format_telegram_message(new_jobs: list[dict[str, Any]], run_date: str) -> list[str]:
    """Return a list of <=4096-char HTML strings ready to POST to Telegram."""
    groups: dict[str, list[dict[str, Any]]] = {c: [] for c in _COUNTRY_ORDER}
    for job in new_jobs:
        groups[bucket_country(job.get("location", ""))].append(job)

    lines: list[str] = []
    lines.append(f"\U0001f514 <b>{len(new_jobs)} new job(s) found \u2014 {run_date}</b>")

    for country in _COUNTRY_ORDER:
        bucket = groups[country]
        if not bucket:
            continue
        emoji = _COUNTRY_EMOJI[country]
        lines.append("")
        lines.append(f"{emoji} <b>{country} ({len(bucket)})</b>")
        for job in bucket:
            company = _escape_text(job.get("company", ""))
            title = _escape_text(job.get("title", ""))
            location = _escape_text(job.get("location", ""))
            posted = _escape_text(job.get("posted", ""))
            url = _escape_url(job.get("url", ""))
            loc_part = f"\U0001f4cd {location}" if location else ""
            date_part = f"\U0001f5d3 {posted}" if posted else ""
            meta = " | ".join(p for p in [loc_part, date_part] if p)
            link = f'<a href="{url}">Apply \u2192</a>' if url else ""
            lines.append("")
            lines.append(f"\u2022 <b>{company} \u2014 {title}</b>")
            if meta:
                lines.append(f"  {meta}")
            if link:
                lines.append(f"  {link}")
    return _chunk_telegram_lines(lines)


def _format_duration(hours: int | None) -> str:
    total_hours = max(0, int(hours or 0))
    days, rem_hours = divmod(total_hours, 24)
    if days and rem_hours:
        return f"{days}d {rem_hours}h"
    if days:
        return f"{days}d"
    return f"{rem_hours}h"


def format_overdue_staging_message(overdue_jobs: list[dict[str, Any]], run_date: str) -> list[str]:
    """Return a list of <=4096-char HTML strings for overdue staging jobs."""
    lines: list[str] = [f"\u23f0 <b>{len(overdue_jobs)} staging job(s) overdue \u2014 {run_date}</b>"]
    for job in overdue_jobs:
        company = _escape_text(job.get("company", ""))
        title = _escape_text(job.get("title", ""))
        location = _escape_text(job.get("location", ""))
        overdue = _format_duration(job.get("overdue_hours"))
        url = _escape_url(job.get("url", ""))
        meta_parts = [f"\u23f1 Overdue by {overdue}"]
        if location:
            meta_parts.append(f"\U0001f4cd {location}")
        lines.append("")
        lines.append(f"\u2022 <b>{company} \u2014 {title}</b>")
        lines.append(f"  {' | '.join(meta_parts)}")
        if url:
            lines.append(f'  <a href="{url}">Review \u2192</a>')
    return _chunk_telegram_lines(lines)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Send a single HTML-formatted message via the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    resp.raise_for_status()


def _send_notification_chunks(
    *,
    token: str,
    chat_id: str,
    chunks: list[str],
    console: Any,
    label: str,
    item_count: int,
) -> None:
    sent = 0
    for i, chunk in enumerate(chunks):
        if i > 0:
            time.sleep(1)  # avoid Telegram rate-limit between chunks
        try:
            send_telegram(token, chat_id, chunk)
            sent += 1
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            if console:
                console.print(f"  [red]Telegram error:[/red] {e}")
    if console and sent:
        console.print(
            f"  [green]Telegram:[/green] sent {sent} message(s) "
            f"for {item_count} {label}"
        )


def notify_new_jobs(
    new_jobs: list[dict[str, Any]],
    token: str,
    chat_id: str,
    console: Any,
) -> None:
    """Format and send Telegram notifications for newly found jobs."""
    run_date = datetime.now(timezone.utc).isoformat()[:10]
    chunks = format_telegram_message(new_jobs, run_date)
    _send_notification_chunks(
        token=token,
        chat_id=chat_id,
        chunks=chunks,
        console=console,
        label="new job(s)",
        item_count=len(new_jobs),
    )


def notify_overdue_staging_jobs(
    overdue_jobs: list[dict[str, Any]],
    token: str,
    chat_id: str,
    console: Any,
) -> None:
    """Format and send Telegram notifications for overdue staging jobs."""
    run_date = datetime.now(timezone.utc).isoformat()[:10]
    chunks = format_overdue_staging_message(overdue_jobs, run_date)
    _send_notification_chunks(
        token=token,
        chat_id=chat_id,
        chunks=chunks,
        console=console,
        label="overdue staging job(s)",
        item_count=len(overdue_jobs),
    )
