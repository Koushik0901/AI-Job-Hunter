# TODO

Priority order reflects dependency and user-facing impact: fix the data supply first,
then the control surfaces over it, then the operator layer on top, then brand-voice
and polish, then risk-heavy hygiene last.

## (1) Solidify scraping pipeline across ATS providers

**Priority: P0 — foundational.** Without working scrapers the whole app is starved of
data: matching, scoring, dashboard, agents all degrade to whatever Greenhouse returns.
The user has confirmed Lever/Ashby/Workable are broken (AltaML example), so this is an
active regression, not a nice-to-have. Every other feature below gets more valuable
once the data supply is fixed. Do this first.

Only Greenhouse seems to fully work. Lever, Ashby, Workable look broken — e.g. AltaML
is in `company_sources` with a valid Lever URL (https://jobs.lever.co/altaml/) but no
jobs land in the `jobs` table.

**Scope:**
- Test each fetcher (`greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `recruitee`, `teamtailor`, `hn`) against a known-good company and assert non-empty results
- Fix Lever/Ashby/Workable fetchers; add regression tests under `tests/` with recorded fixtures
- Review Career-Ops GitHub repo for its crawl strategy and source list — steal what's useful
- Evaluate scraping Wellfound (AngelList Talent) — check ToS, feasibility, auth requirements
- Add a `sources check-all` CLI subcommand that pings every configured source and reports coverage

## (2) Sources & companies management UI

**Priority: P1 — tight coupling to (1).** Once the fetchers work, the user needs to
see *which* sources/companies are healthy and control them without editing
`companies.yaml` by hand. Without this, (1) remains opaque — a fetcher could silently
break again and nobody would notice. Also prerequisite for (4): the agent needs these
endpoints to do "add a company" or "pause this source" via tool calls.

**Scope:**
- Backend: CRUD endpoints for `company_sources` (add, remove, enable/disable toggle, edit ATS config)
- Backend: endpoint to toggle entire ATS providers on/off (e.g. pause all Lever scrapes)
- Frontend: new settings screen or Profile tab section listing companies with enable/disable toggles, remove button, "Add company" flow (reuse `add_company.py` ATS-discovery logic)
- Wire `companies.yaml` → DB sync so UI edits persist (decide: YAML as source of truth, or DB)
- Show last-scraped timestamp + job count per company

## (3) Settings screen — integrations, models, API keys

**Priority: P1 — unblocks non-technical users and hosted-instance friends.** The
`.impeccable.md` secondary-user persona ("non-technical friends on a hosted instance")
cannot edit `.env`. Also unlocks the agent's "configure Telegram / set model" tool
calls in (4) by giving them a real backend to write to. Parallelizable with (2) —
different surface area, no blocking dependency.

Let the user configure the stuff that currently lives in `.env` through the UI.

**Scope:**
- Telegram (or alternative messaging: Discord, Slack, email) — connect flow, test-send button
- OpenRouter API key input with validation
- Model pickers for `ENRICHMENT_MODEL`, `DESCRIPTION_FORMAT_MODEL`, `SLM_MODEL`, `LLM_MODEL`, `EMBEDDING_MODEL` (populated from OpenRouter `/models` endpoint)
- Timezone picker (`JOB_HUNTER_TIMEZONE`)
- Secure storage: encrypt API keys at rest in DB, never return in GET responses (mask)
- Backend: secrets table + getter that falls back to env var if DB row absent

## (4) Truly agentic Command page

**Priority: P1 — product differentiator, but intentionally after (2) and (3).** The
agent is the headline feature, but it can only do what the backend exposes. Building
it before (2)/(3) means either stubbing tools that don't work, or doing the CRUD work
twice. Once sources + settings endpoints exist, the agent is a thin orchestration
layer over them. Also the approval UX (terracotta moment) is already speced — the
blocker is backend tool coverage, not frontend.

The Command screen should be the core operator — capable of doing anything in the app
end-to-end, not just chatting. Expand tool coverage in `agent_gateway/agent_tools.py`.

**Scope:**
- Pipeline ops: move jobs across stages (`not_applied` → `applied` → `interview` → ...), bulk-apply stage changes
- Sources ops: add/remove/toggle companies in `company_sources` via tool calls (depends on (2))
- Artifact ops: generate/tailor resumes + cover letters for a specific job (already partial — finish it)
- Integration ops: configure Telegram token, trigger test notification, set model env vars (depends on (3))
- Scraping ops: trigger a scrape run, check source health, re-enrich a job
- Profile ops: edit candidate profile fields, bump `score_version`
- Each tool needs: LangChain `Tool` spec, approval gate for destructive ops (terracotta moment per design), streaming status back to the UI

## (5) Daily score recompute for time-decayed ranking

**Priority: P1 — corrupts daily ranking silently.** `match_score.py::_recency_multiplier`
exists but only runs at score-write time and is then frozen in `job_match_scores`.
Today, recompute happens only on profile mutation (`bump_candidate_profile_score_version`),
explicit per-URL recompute (after manual add or re-enrich), or when the snapshot table
is empty. So a job whose recency factor was 1.00 yesterday stays at 1.00 forever — a
month-old role in Discover can outrank a fresh one because no pass ever re-evaluates
the time term. This quietly degrades the `.impeccable.md` "3–10 roles worth reading"
promise. Same priority tier as (1)/(2) because it affects what the user sees every day.

**Freeze rule.** Recompute only the **backlog** — jobs in `not_applied` or `staging`.
Once a job moves to `applied`, `interviewing`, `offer`, or `rejected`, the score is
frozen at whatever it was when the user committed to that role. Re-ranking a role
you've already submitted to is meaningless and would make the Pipeline screen feel
restless. The score on those cards is a historical record, not a live signal.

**Scope:**
- Add a `recompute-scores` CLI subcommand that runs `recompute_match_scores(conn)`
  scoped to jobs whose tracking status is `not_applied` or `staging` (excluding
  suppressed); refreshes `job_dashboard_snapshots` for the same set
- Wire a daily GitHub Actions workflow (e.g. `score_refresh.yml`) that runs after the
  enrichment workflow — leverages existing `daily_scrape.yml` / `enrichment.yml` cadence
- Confirm `recompute_match_scores()` honours the status filter (it currently takes a
  `urls=` filter; may need a `statuses=` filter or pre-filter the URL list)
- Identify any other score components that should evolve with time (urgency, staging
  age, last-seen freshness, "posted recently" reasons) and confirm they read the
  current date when the recompute runs, not the cached value
- Beware CLAUDE.md gotcha: `INSERT OR REPLACE INTO job_match_scores` wipes
  `reasoning_blurb`. Pass `recompute=False` to `refresh_dashboard_snapshots` paths that
  only touched adjacent columns, OR re-emit blurbs after the recompute
- Add a backfill flag so the first run can recompute every backlog row
- Telemetry: log how many rows changed band/score so we can spot dead recencies

## (6) Job detail drawer + event timeline

**Priority: P1 — foundation for half the items below.** Today clicking a card on
Pipeline or Discover does nothing. The `job_events` table exists with structured event
types (`note`, `recruiter_screen`, `technical_interview`, `offer`, `rejection`) and a
backend CRUD, but no UI consumes them. Until a focused detail surface exists, items
(7), (8), (9), (15), and the future "why this score changed" diff have nowhere to
live. Build this first among the new P1s.

A side drawer that slides in from the right (or a modal on small viewports) when a
card is clicked, anchored to the existing `JobDetail` API.

**Scope:**
- Drawer component in `kenji/` — sage left-rail, full-height, ~min(560px, 90vw), Esc/click-outside to close, focus trap, body scroll lock
- Sections: header (logo, company, role, location, score ring, recommendation band), reformatted job description (collapsible), score breakdown (raw/rank, reasons, calibration band), event timeline (read from `/api/jobs/{id}/events`), notes, artifacts list, suppress/unsuppress action
- Click handler on `PipelineCard` and `DiscoverCard` to open the drawer with that job's id; URL hash sync (`#/pipeline?job=<id>`) so links are shareable and refresh-safe
- Re-use existing endpoints: `/api/jobs/{id}` (detail), `/api/jobs/{id}/events` (timeline), `/api/jobs/{id}/artifacts` (artifacts), `/api/jobs/{id}/suppress`
- Reading view toggle on the description: centered typography, max ~72ch, sage italic for emphasis — leans into the editorial-magazine brand
- Empty timeline state: "no events yet — Kenji will log automatic ones; add a note to start the trail."

## (7) Pipeline interactivity — wire the dead toolbar

**Priority: P1 — central screen, but most controls are decorative.** The Pipeline
toolbar has buttons that don't do anything: `All` / `My turn` / `This week` /
`>= 85 match` filters don't filter, `Columns` doesn't toggle column collapse, the
insight-panel buttons (`Run agent on pipeline`, `Draft follow-ups`, `Review staging`)
don't fire. The cards themselves don't open detail. This makes a brand-critical
screen feel like a mockup. Card movement is split out into (8) so this item stays
focused on the toolbar / filters / detail-open wiring.

**Scope:**
- Filter chips: implement `All` (no-op), `My turn` (rows where last event was theirs / awaiting user action), `This week` (`updated_at` within 7 days), `>= 85 match` (rank score >= 85). Persist active filter in URL hash so refresh-safe
- `Columns` toggle: collapse/expand individual stage columns (the `compact` prop already exists in `Column`); persist collapsed-set in localStorage
- Insight-panel actions: `Run agent on pipeline` should fire an agent task scoped to the current pipeline (depends on (4)), `Draft follow-ups` should generate follow-up cover-letter snippets for stale `applied` rows (depends on (4) + (10)), `Review staging` should focus the staging column and filter to its rows
- Click-card → open job detail drawer from (6)
- Replace the dead "nothing here yet" empty state with stage-specific copy ("nothing in motion. start in Discover.", "no offers yet. keep going.", etc.)
- Don't introduce a second primary CTA — the brand brief allows one per view, and `Run agent` already holds it

## (8) Drag-and-drop + right-click context menu on Pipeline

**Priority: P1 — direct-manipulation gap.** Currently the operator has no way to move
a card between stages from the UI; only the agent can. This is the most jarring
mismatch with kanban affordances people expect. Pair with a shadcn-style `ContextMenu`
on right-click for the actions that don't deserve a button.

**Scope:**
- Drag-and-drop: pick a small lib (`@dnd-kit/core` or `react-beautiful-dnd` — prefer dnd-kit, actively maintained) and wire it to `Column` + `PipelineCard`. Drop fires `PATCH /api/jobs/{id}/tracking { status }`. Optimistic update + rollback on failure (mirror the manual-add pattern that just shipped)
- Visual: subtle ghost card at original position, sage drop target highlight on hover, no bounce/spring (brand brief: "no spring, no overshoot"). Honour `prefers-reduced-motion`
- Context menu (right-click on a card): build a `ContextMenu` component matching shadcn's anatomy (radix-ui primitives if added, or hand-rolled). Items:
  - `Open detail` (opens drawer from (6))
  - `Move to →` submenu (Staging, Applied, Interviewing, Offer, Closed)
  - `Add note`
  - `Suppress this role` — terracotta colour, with confirm
  - `Delete from pipeline` — terracotta colour, hard delete with confirm. Hits a new `DELETE /api/jobs/{id}` endpoint; need to decide whether this also removes the underlying `jobs` row or just untracks it (proposal: untrack + suppress URL so it doesn't re-appear)
  - `Copy posting URL`
  - `Open posting in new tab`
- Keyboard parity: enter to open detail, m to open move submenu, d to suppress, x to delete (so right-click users and keyboard users have the same affordances — see future shortcuts work)
- Accessibility: `role="menu"` + roving tabindex, dismiss on Escape, return focus to card

## (9) Right-click context menu on Discover

**Priority: P1 — consistency with (8) and unblocks fast triage.** Discover is the
"3–10 roles worth reading" entry point but today it's a passive list. Right-click on a
job card should give the operator the same shadcn-style menu as Pipeline, tuned to the
Discover-stage actions.

**Scope:**
- Reuse the `ContextMenu` component from (8) with a Discover-specific item set:
  - `Open detail` (drawer from (6))
  - `Move to staging` — promotes the job to the kanban staging column
  - `Mark as applied` (skips staging — for jobs the user applied to outside Kenji)
  - `Suppress this role` — terracotta, with confirm
  - `Hide for now` (soft hide, surfaced again next week — tracks last_dismissed)
  - `Copy posting URL`
  - `Open posting in new tab`
- All actions use existing endpoints; no new backend except possibly a `dismissed_until`
  column on `job_tracking` (or a side table) for "hide for now"
- Same a11y rules as (8): keyboard parity, focus management, role/aria attrs

## (10) Daily briefing screen — the home view

**Priority: P1 — completes the brand promise.** The product narrative is "Kenji
watches while you're away" but there's no UI that surfaces what changed. The
`daily-briefing` CLI exists and Telegram receives the digest, but the dashboard
doesn't have a "today's read" landing. The secondary persona ("non-technical friends")
currently lands on Discover with 239 rows and no guide — this screen is supposed to be
where they start.

**Scope:**
- New screen `kenji/Briefing.tsx`, route key `briefing`. Make it the default screen
  on first visit (override the localStorage screen-key once)
- Sections:
  - "Today's read" — top 3–10 backlog jobs ranked by current score, with one-sentence reason each (reuse `recommendation_reasons[0]` or generate fresh blurb)
  - "What changed since you were last here" — new postings, score deltas (depends on (5)), status moves logged in `job_events`
  - "Pending your turn" — applied jobs where days_since > a threshold and no recruiter signal yet
  - "Scheduled" — interviewing jobs with upcoming events
- Backend: tighten `daily_briefing.py` so it returns structured JSON (it's currently text-oriented for Telegram); add `GET /api/briefing` endpoint that the screen calls
- Empty states are critical here — first-time user has no data: "Kenji's still learning your taste. Run a scrape, check back tomorrow."
- Cache the response with a short TTL (10–15 min) since it's read-heavy

## (11) Markdown-resume as the base resume standard

**Priority: P2 — quality/consistency, not blocking.** Resume Lab works today; this is
a schema-standardization upgrade that makes tailoring, imports, and PDF export
coherent. Doing it after (4) means the agent's artifact tools emit the right schema
from day one. Doing it before (4) means retrofitting those tools twice.

Adopt https://github.com/junian/markdown-resume as the canonical resume format across
the app. All tailoring, agent output, profile imports, and the Resume Lab screen
should produce/consume this schema.

**Scope:**
- Vendor or fork the markdown-resume template into the repo
- Update Resume Lab to edit in this format (Markdown editor + live preview)
- Update resume artifact generation prompts to emit this exact structure
- Update Profile page resume-import to parse markdown-resume format
- Update PDF export (fpdf2) to render the markdown-resume template faithfully
- Add a validator that rejects generated resumes that don't conform

## (12) Empty / error / loading states with brand voice

**Priority: P2 — small surface, high brand-presence.** Right now only the boot screen
is branded; everything else falls back to generic spinners and "nothing here yet"
placeholders. Errors today are stack-trace-flavored alerts. `.impeccable.md` says
"teach on empty" — every empty state is a teaching opportunity, every error is a
chance to feel calm instead of broken. This item is voice + copy + small components,
not a new system.

**Scope:**
- Audit every screen for empty/error/loading states; build a shared `EmptyState`,
  `ErrorState`, and `LoadingState` set in `kenji/ui.tsx` consistent with the existing
  `boot-screen` vocabulary
- Empty states explain the screen in one sentence + one CTA; no illustrations
  (anti-reference: Indeed/LinkedIn)
- Error copy: short, calm, named (e.g. "Kenji lost the thread for a moment.
  Retry?"). Never expose stack traces in production
- Loading variants: boot-bar shimmer for first-load, inline pulse for refetches,
  skeleton row for list pagination — all honour `prefers-reduced-motion`
- Replace every `window.alert(...)` (including the one I shipped in the manual-add
  modal) with a tiny in-app toast + log to console

## (13) Hosted-instance onboarding

**Priority: P2 — secondary persona has zero scaffolding.** `.impeccable.md` calls out
"non-technical friends on a hosted instance" who "have never heard of
Greenhouse/Ashby." They land on Discover and bounce. Pairs naturally with (3)
Settings — onboarding is essentially the first-run wizard wrapping the settings flow.

**Scope:**
- Detect first run (no `candidate_profile.full_name`, no `OPENROUTER_API_KEY` set,
  empty `company_sources` user rows)
- Guided five-step flow: (a) what is Kenji (one paragraph + a single image-free
  illustration in sage type), (b) connect Telegram or skip, (c) paste OpenRouter key
  (or use hosted default), (d) seed 5 favourite companies (autocomplete from
  `add_company.py` ATS-discovery), (e) pick desired roles + Canada/remote pref
- Last step kicks off the first scrape and lands the user on the daily briefing (10)
  with empty-state copy
- Skippable at every step; user can finish later from Profile
- Persist completion flag in `candidate_profile.onboarding_completed_at`

## (14) Accessibility audit & fixes

**Priority: P2 — claimed compliance, unverified.** `.impeccable.md` claims WCAG 2.2
AA. From a quick scan there are real gaps: `ScoreRing` has no aria-label or text
fallback, `BarMeter` same, status pills convey meaning by colour alone, the manual-add
modal I just shipped has no focus trap, `aria-live="polite"` for agent state isn't
wired, no skip-to-content link. `.impeccable.md` is explicit that color-blind users
must get state via icon/label/position too.

**Scope:**
- ScoreRing: `role="img"` with `aria-label="Match score: 79 of 100"`; honour
  `prefers-reduced-motion` for the draw animation (already partial)
- BarMeter: `role="progressbar"` with `aria-valuenow/min/max` and `aria-label`
- Status pills, recommendation bands, match-bands: pair colour with icon and text;
  audit per `.impeccable.md` "no state by colour alone"
- Modal focus traps: implement on the manual-add modal (mine), agent approval modals,
  and any future drawer (item (6))
- Agent voice: `aria-live="polite"` on the Command screen so screen readers announce
  assistant replies
- Skip-to-content link at top of every screen (visible on focus)
- `prefers-reduced-motion`: confirm the global block in `styles.css` actually kills
  every animation on each screen (boot bar, score ring draw, bar meter sweep, funnel
  bar entry, button :active scale, chip removal fade, job-card expand, typing dots,
  shimmer, pulse — listed in MEMORY.md)
- Run axe-core in CI against the built bundle; fail on violations

## (15) Suppress / decision history surface

**Priority: P2 — backend exists, no UI.** `job_suppressions`, `job_events`, and
`/api/jobs/{id}/decision` are all live but invisible to the operator. They can't
permanently hide spammy postings, can't see why a job was rejected/withdrawn, can't
audit their own decisions. Ties to "groundedness over polish" — every state change
should be auditable.

**Scope:**
- Surface "Suppress" in the (8)/(9) context menus with a brief reason input
- New "Suppressed" tab on Profile or a small Settings sub-screen, listing all
  `job_suppressions` rows with company/title/URL/reason/created_at, with an
  "Unsuppress" button per row
- Job detail drawer (6) shows the full event timeline including
  `application_submitted`, `recruiter_screen`, `technical_interview`, `offer`,
  `rejection`, `closed_no_response`, `withdrawn`
- "Add event" affordance in the drawer for manual entries (e.g. logging a recruiter
  reply you got over LinkedIn)
- Closed/rejected jobs in the kanban surface their `decision` reason via a small
  italic line on the card body — preserves grounding without adding noise

## (16) Autofill HITL + learning loop

**Priority: P2 — valuable but narrow.** Only helps users who are actively submitting
applications through the Chrome extension, and only improves over time. Doesn't
unblock any other work. Parked behind the scraping/control/agent stack because those
affect every user on every session.

After the Chrome extension autofills a form, show a confirmation step so the user
can review and correct individual fields before submitting. Persist corrections back
to the system (profile or per-job overrides) so future autofills improve over time.

**Scope:**
- Extension: post-autofill confirmation UI (side panel or overlay) listing filled fields
- User can edit any field inline before confirming
- On confirm, diff corrected fields against filled values and POST corrections to backend
- Backend: store per-field corrections keyed by (job_id or ats_domain, field_name)
- Use stored corrections to pre-seed future autofill for same ATS

## (17) Turso schema cleanup

**Priority: P3 — hygiene, risk-heavy, zero user-facing value.** Dropping tables on the
live DB is irreversible and the blast radius touches every read path. Worth doing
*last*, after the items above have stabilized and any tables they need are obviously
load-bearing. Rushing this before the schema settles risks dropping something that
(2), (4), (6), or (15) was about to need.

A lot of tables on Turso look unnecessary now. Audit the live schema and drop tables
that are no longer read/written by any code path. Cross-reference against `db.py`,
`repository.py`, `service.py`, and the agent gateway before dropping.

**Scope:**
- Enumerate all tables on Turso; grep each name across `src/` to find references
- Produce a drop list with justification per table
- Write a dedicated migration script (not `init_db()` ALTER) to drop unused tables
- Back up the DB before running; run against a local copy first
