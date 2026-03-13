# Telegram Integration

Telegram is used for scrape notifications.

---

## Required Env

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

---

## Behavior

- New jobs are summarized and posted.
- Jobs still in `staging` after 48 hours are summarized and posted as a separate alert.
- Overdue staging alerts can send even when a scrape finds zero new jobs.
- Overdue staging alerts repeat on later scrape runs until the job leaves `staging`.
- Notification stage can be disabled with `--no-notify`.

---

## Verification

Run scrape with notifications enabled and confirm:

- new jobs appear in the existing new-jobs message
- overdue staging jobs appear in a separate Telegram message
- overdue-only runs still send the overdue alert
