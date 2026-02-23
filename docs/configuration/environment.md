# Environment Configuration

This project loads environment variables from two sources:

1. existing process environment
2. optional `.env` file via `_load_dotenv` (`os.environ.setdefault`, so existing process values win)

## Variables

| Name | Required | Used by | Notes |
|---|---|---|---|
| `TELEGRAM_TOKEN` | for notifications | `src/notify.py` | Bot token |
| `TELEGRAM_CHAT_ID` | for notifications | `src/notify.py` | Chat target |
| `TURSO_URL` | optional | `src/db.py`, `src/scrape.py` | If set, overrides `--db` local path |
| `TURSO_AUTH_TOKEN` | required with Turso | `src/db.py` | Bearer token for hrana HTTP pipeline |
| `OPENROUTER_API_KEY` | optional | `src/enrich.py`, `eval/eval.py` | Enables enrichment/eval API calls |
| `ENRICHMENT_MODEL` | optional | `src/scrape.py` | Runtime default is `openai/gpt-oss-120b` |

## Precedence and defaults

- If `TURSO_URL` exists: use Turso regardless of `--db`.
- If `TURSO_URL` absent:
  - `--db PATH` if supplied
  - else default `<cwd>/jobs.db`
- If `OPENROUTER_API_KEY` missing:
  - scrape run continues but enrichment stage is skipped
  - eval `run` exits with error

## Security

- `.env` is git-ignored.
- Do not commit live tokens or chat IDs.
- For GitHub Actions, use repo secrets instead of `.env`.

## GitHub Actions secrets

Expected secret names in `.github/workflows/daily_scrape.yml`:

- `TURSO_URL`
- `TURSO_AUTH_TOKEN`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `OPENROUTER_API_KEY`
