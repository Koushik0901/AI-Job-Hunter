# 🚀 Telegram Integration

Telegram is used for new-job notifications from scrape flows.

---

## ✨ Required Env

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

---

## ✨ Behavior

- New jobs are summarized and posted.
- Notification stage can be disabled with `--no-notify`.

---

## ✨ Verification

Run scrape once with notifications enabled and confirm message delivery in target chat.
