# 🚀 Known Issues

Fast answers to common breakpoints.

---

## `GET /api/profile` or `/api/jobs` returns 500 during startup

Usually schema drift in DB migrations/indexes.

Action:
- run backend once and inspect migration errors
- verify current DB has expected columns/indexes

---

## ✨ Swarm run applies few edits

Usually strict policy gates (claim/citation/region) are filtering most moves.

Action:
- inspect run events -> `verify_moves` + `apply` failures
- inspect `failed_move_reasons`

---

## ✨ Compile failures after AI edits

Action:
- check compile diagnostics
- verify unescaped symbols and brace balance
- rely on compile-guard rollback for final safety

---

## ✨ Benchmark dataset has unexpectedly low case count

Cause:
- dataset builder filters on JD/artifact availability

Action:
- use latest builder (supports fallback LaTeX seed)
- broaden statuses and increase limit
