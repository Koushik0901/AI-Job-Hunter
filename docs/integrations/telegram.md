# Telegram Integration

Implemented in `src/notify.py`.

## Functions

- `_load_dotenv(path)`: minimal KEY=VALUE loader
- `bucket_country(location)`: `Canada` / `USA / Remote` / `Other`
- `format_telegram_message(new_jobs, run_date)`: grouped HTML message chunks
- `send_telegram(token, chat_id, text)`: POST to Bot API
- `notify_new_jobs(...)`: sends all chunks with 1s delay between chunks

## Message behavior

- Header includes job count and UTC run date.
- Jobs grouped by country bucket.
- Uses HTML formatting (`parse_mode=HTML`).
- Enforces Telegram message length cap (4096 chars) by chunking.

## Delivery behavior

- Only new jobs trigger notifications in scrape flow.
- Missing token/chat id prints guidance and skips send.
- send exceptions are logged; pipeline continues.
