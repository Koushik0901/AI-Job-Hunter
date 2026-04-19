"""
notify.py — country bucketing and Telegram notification helpers.
"""
from __future__ import annotations

import hashlib
import html
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from ai_job_hunter.config import get_locations, notifications_enabled
from ai_job_hunter.env_utils import load_dotenv as _shared_load_dotenv, local_timezone as _local_timezone

logger = logging.getLogger(__name__)

_DEFAULT_FALLBACK_BUCKET = "Other"


def _notification_timezone():
    return _local_timezone()


def _load_dotenv(path: Path) -> None:
    _shared_load_dotenv(path)


def _notification_buckets() -> list[dict[str, Any]]:
    buckets = get_locations().get("notification_buckets") or []
    return [b for b in buckets if isinstance(b, dict) and b.get("name")]


def _country_emoji_map() -> dict[str, str]:
    emojis = get_locations().get("country_emoji") or {}
    return {str(k): str(v) for k, v in emojis.items() if v}


def _bucket_order() -> list[str]:
    buckets = _notification_buckets()
    if not buckets:
        return [_DEFAULT_FALLBACK_BUCKET]
    return [str(b["name"]) for b in buckets]


def bucket_country(location: str) -> str:
    """Classify a free-text location string using configured notification_buckets."""
    loc = location.lower()
    stripped = location.strip()
    buckets = _notification_buckets()
    fallback = _DEFAULT_FALLBACK_BUCKET
    for bucket in buckets:
        name = str(bucket["name"])
        if bucket.get("fallback"):
            fallback = name
            continue
        if not stripped and bucket.get("match_empty"):
            return name
        signals = [str(s).lower() for s in (bucket.get("match_any") or []) if str(s).strip()]
        if any(sig in loc for sig in signals):
            return name
    return fallback


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


def telegram_message_hash(chunks: list[str]) -> str:
    return hashlib.sha1("\n".join(chunks).encode("utf-8")).hexdigest()


def format_telegram_message(new_jobs: list[dict[str, Any]], run_date: str) -> list[str]:
    """Return a list of <=4096-char HTML strings ready to POST to Telegram."""
    order = _bucket_order()
    emoji_map = _country_emoji_map()
    groups: dict[str, list[dict[str, Any]]] = {c: [] for c in order}
    for job in new_jobs:
        bucket_name = bucket_country(job.get("location", ""))
        groups.setdefault(bucket_name, []).append(job)

    lines: list[str] = []
    lines.append(f"\U0001f514 <b>{len(new_jobs)} new job(s) found \u2014 {run_date}</b>")

    for country in order:
        bucket = groups.get(country, [])
        if not bucket:
            continue
        emoji = emoji_map.get(country, "\U0001f30d")
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


def format_daily_briefing_message(briefing: dict[str, Any]) -> list[str]:
    brief_date = _escape_text(briefing.get("brief_date") or "")
    summary_line = _escape_text(briefing.get("summary_line") or "")
    apply_now = list(briefing.get("apply_now") or [])
    follow_ups_due = list(briefing.get("follow_ups_due") or [])
    watchlist = list(briefing.get("watchlist") or [])
    profile_gaps = [str(item).strip() for item in list(briefing.get("profile_gaps") or []) if str(item).strip()]
    signals = [str(item).strip() for item in list(briefing.get("signals") or []) if str(item).strip()]
    quiet_day = bool(briefing.get("quiet_day"))

    lines: list[str] = [f"\U0001f4cc <b>Daily briefing \u2014 {brief_date}</b>"]
    lines.append(summary_line or ("Quiet day: no urgent actions." if quiet_day else "Daily action summary."))

    if apply_now:
        lines.append("")
        lines.append("\U0001f680 <b>Apply now</b>")
        for item in apply_now:
            company = _escape_text(item.get("company") or "")
            title = _escape_text(item.get("title") or "")
            reason = _escape_text(item.get("reason") or "")
            score = item.get("score")
            url = _escape_url(item.get("job_url") or "")
            score_text = f" \u00b7 score {score}" if isinstance(score, int) else ""
            lines.append(f"\u2022 <b>{company} \u2014 {title}</b>{score_text}")
            if reason:
                lines.append(f"  {reason}")
            if url:
                lines.append(f'  <a href="{url}">Open \u2192</a>')

    if follow_ups_due:
        lines.append("")
        lines.append("\u23f0 <b>Follow-ups due</b>")
        for item in follow_ups_due:
            company = _escape_text(item.get("company") or "")
            title = _escape_text(item.get("title") or "")
            due_at = _escape_text(item.get("due_at") or "")
            reason = _escape_text(item.get("reason") or "")
            url = _escape_url(item.get("job_url") or "")
            lines.append(f"\u2022 <b>{company} \u2014 {title}</b>")
            if due_at or reason:
                meta = " | ".join(part for part in [f"Due {due_at}" if due_at else "", reason] if part)
                if meta:
                    lines.append(f"  {meta}")
            if url:
                lines.append(f'  <a href="{url}">Review \u2192</a>')

    if watchlist:
        lines.append("")
        lines.append("\U0001f440 <b>Watchlist</b>")
        for item in watchlist[:3]:
            company = _escape_text(item.get("company") or "")
            title = _escape_text(item.get("title") or "")
            reason = _escape_text(item.get("reason") or "")
            lines.append(f"\u2022 <b>{company} \u2014 {title}</b>")
            if reason:
                lines.append(f"  {reason}")

    if profile_gaps:
        lines.append("")
        lines.append("\U0001f9e9 <b>Top gaps</b>")
        for gap in profile_gaps[:2]:
            lines.append(f"\u2022 {_escape_text(gap)}")

    if signals:
        lines.append("")
        lines.append("\U0001f4ca <b>Signals</b>")
        for signal in signals[:2]:
            lines.append(f"\u2022 {_escape_text(signal)}")

    return _chunk_telegram_lines(lines)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    """Send a single HTML-formatted message via the Telegram Bot API."""
    if not notifications_enabled():
        logger.info("Notifications disabled in profile; skipping Telegram send")
        return
    if not token or not chat_id:
        logger.info("Telegram token/chat_id missing; skipping send")
        return
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
    run_date = datetime.now(_notification_timezone()).date().isoformat()
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
    run_date = datetime.now(_notification_timezone()).date().isoformat()
    chunks = format_overdue_staging_message(overdue_jobs, run_date)
    _send_notification_chunks(
        token=token,
        chat_id=chat_id,
        chunks=chunks,
        console=console,
        label="overdue staging job(s)",
        item_count=len(overdue_jobs),
    )


def notify_daily_briefing(
    briefing: dict[str, Any],
    token: str,
    chat_id: str,
    console: Any,
) -> list[str]:
    chunks = format_daily_briefing_message(briefing)
    _send_notification_chunks(
        token=token,
        chat_id=chat_id,
        chunks=chunks,
        console=console,
        label="daily briefing chunk(s)",
        item_count=len(chunks),
    )
    return chunks
