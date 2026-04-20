<div align="center">

# AI Job Hunter

### A job-search workflow system built to turn scattered listings into a disciplined application pipeline

<p>
  <img alt="Python backend" src="https://img.shields.io/badge/backend-python-1f3b73?style=for-the-badge">
  <img alt="React frontend" src="https://img.shields.io/badge/frontend-react-0f172a?style=for-the-badge">
  <img alt="Redis caching" src="https://img.shields.io/badge/cache-redis-7f1d1d?style=for-the-badge">
  <img alt="AI-assisted enrichment" src="https://img.shields.io/badge/workflow-ai--assisted-243b2f?style=for-the-badge">
</p>

</div>

---

> **Why this exists**
>
> I built AI Job Hunter after realizing that job boards are good at discovery, but weak at helping a candidate actually manage the work that starts after a good role is found.

## The Problem

My real workflow looked something like this:

1. search across LinkedIn, Indeed, Himalayas, Workopolis, and direct company career pages  
2. open promising roles one by one  
3. copy descriptions into ChatGPT to understand fit and prep application work  
4. track applications and follow-ups in tabs, notes, and memory  
5. come back later and reconstruct what had already been done

That process created the same friction over and over:

| What broke | Why it mattered |
| --- | --- |
| Jobs were scattered across too many sources | High-signal roles were easy to lose in volume |
| Descriptions were noisy and inconsistent | Comparing opportunities quickly was harder than it should have been |
| Application status lived in my head | Follow-ups and next actions became unreliable |
| "Interesting" and "active pipeline" blurred together | Good opportunities were not getting structured attention |
| There was no daily operating view | The search felt reactive instead of intentional |

AI Job Hunter is my attempt to solve that like a systems problem, not just a note-taking problem.

## What I Built

The product combines sourcing, workflow management, and assistant-style prioritization into one system.

The current frontend is organized around distinct workflow surfaces instead of overlapping dashboards:

| Route | Purpose |
| --- | --- |
| `Today` | short daily operating brief |
| `Board` | pipeline operations and detailed job review |
| `Discover` | ranked intake feed for strong unopened roles |
| `Apply` | chat-first application workspace with an action canvas |
| `Strategy` | search pattern review and course correction |
| `Settings` | profile and document base |

<table>
  <tr>
    <td valign="top" width="33%">

### Today

The operational brief.

- daily operating summary
- must-do-now actions
- follow-ups due
- lower-urgency review lane
- top signals and quiet-day guidance

Built to answer:

- what should I do now?
- what can wait?
- what changed since last check?

    </td>
    <td valign="top" width="33%">

### Board

The pipeline workspace.

- Kanban and list views
- search, filters, and focus modes
- manual add
- duplicate-aware job creation
- drag-and-drop stage movement
- rich job drawer

    </td>
    <td valign="top" width="33%">

### Insights

The search review page.

- pipeline health and conversion funnel
- pipeline mix visualization
- opportunity quality visualization
- source performance bars
- profile blockers (linked to board search)
- role family response patterns
- targeting signals: where to shift focus
- AI strategy notes

    </td>
  </tr>
</table>

<table>
  <tr>
    <td valign="top" width="33%">

### Discover

A ranked recommendation queue.

- strong unopened opportunities
- cohort-calibrated rank feed
- direct queueing into the application workflow
- scoped skill-gap summaries for the current recommendation set

    </td>
    <td valign="top" width="33%">

### Apply

The chat-first application studio.

- compact queued-role context
- slash-skill commands for `/discover`, `/resume`, `/cover-letter`, and `/critique`
- persistent action canvas for discovery results, tailored documents, and critiques
- artifact editing with streaming generation and PDF export without leaving the workflow
- ATS critique panel: keyword gap analysis with one-click revised resume apply

    </td>
    <td valign="top" width="33%">

### Chrome Extension

Form filling for ATS.

- auto-fill Greenhouse, Lever, Ashby, Workable, SmartRecruiters
- upload tailored resume/cover letter PDFs directly to file inputs
- side panel for quick job review

    </td>
  </tr>
</table>

## What Makes It Useful

This is not just a list of saved links.

It is designed to reduce workflow overhead during an active search:

- manually added jobs open immediately while enrichment and recommendation work continue in the background
- duplicates are detected and reused instead of silently multiplying
- job descriptions are normalized before enrichment and storage
- recommendations change based on application stage
- daily briefing and action queues compress a large backlog into a smaller set of concrete actions
- dashboard reads are snapshot-backed so browsing and queue work stay responsive while background jobs continue

## Why This Is Stronger Than a Normal Job Board

Job boards optimize for listing discovery.

This project is built for what happens *after* discovery:

| Job boards usually help with | AI Job Hunter is built for |
| --- | --- |
| finding listings | evaluating and prioritizing opportunities |
| browsing roles | tracking a real application pipeline |
| one listing at a time | cross-source comparison and workflow continuity |
| passive search | deliberate daily execution |

## What This Demonstrates

For a technical recruiter or hiring manager, this project is meant to show how I approach software:

- I build from a real operational problem
- I design workflows, not just isolated screens
- I care about reliability details like retries, duplicate control, caching, and async processing
- I use AI for leverage, but I still design the surrounding product and state model carefully
- I like turning messy human processes into software that is calmer and more structured to use

## Current Capabilities

### Manual add

- required fields are clearly marked
- save opens the job immediately
- duplicates reopen the existing record
- enrichment, formatting, and recommendation work continue after save
- failed background processing can be retried from the drawer

### Background processing

Jobs expose a compact processing state:

- `processing`
- `ready`
- `failed`

### Recommendation model

- `raw_fit` measures content alignment against the profile
- `rank_score` calibrates that fit against the active cohort so top scores stay rare and meaningful
- `recommendation` stays stage-aware and blends fit, urgency, friction, confidence, and light historical signals
- progressed jobs no longer show misleading early-stage interview framing
- `Recommend` and `Insights` present recommendation context as rank plus reasoning, not a fake percent-fit

### Insights visuals

The `Insights` page keeps the calmer narrative layout while still providing fast-read visual analysis:

- tracked pipeline composition donut
- rank distribution and fit analysis
- funnel and source-performance visuals that support weekly course correction

### Apply workspace

The `Apply` page is now structured as a co-pilot studio instead of a queue-first utility page:

- left pane is the dominant interaction surface for conversation, slash skills, and current-role context
- right pane is a quieter action canvas that keeps the latest tangible result visible
- advisory chat replies stay in the thread rather than wiping the current output
- the page follows the calmer Ethereal Navigator direction with spatial hierarchy, tonal depth, and more restrained gradient use

### Performance model

The dashboard now uses a fast read path plus background work:

- snapshot-backed list reads for jobs, stats, recommendations, and assistant surfaces
- browser memory reuse plus shared client-side caches for bootstrap, jobs, queue, detail, events, and artifacts
- `ETag`-based HTTP revalidation and Redis-backed server-side caching
- `stale-while-revalidate` reads plus live SSE invalidation for background updates
- deterministic fast-agent replies for common prompts before LLM fallback
- smart model routing: simple queries use a fast SLM; generation, analysis, and long messages auto-route to the strong model

### Design system

The dashboard uses a formal design system called **The Navigator**:

- **Brand personality**: Authoritative, Calm, Disciplined
- **Fonts**: "Plus Jakarta Sans" (headings) + "Inter" (body)
- **Color**: Violet accent (`#630ed4`), tonal layering (surface-0 to surface-3)
- **Accessibility**: Universal `prefers-reduced-motion` support, global `:focus-visible` rings
- **Source of truth**: `.impeccable.md` contains the formal design context
- **Page benchmark**: `Board` and dedicated job detail pages are the visual reference for the calmer, premium frontend direction

## Stack

| Layer | Tools |
| --- | --- |
| Frontend | React, Vite, TypeScript |
| Backend | Python (FastAPI) |
| Data / storage | SQLite or Turso |
| Cache | Redis |
| Workflow | scraping, enrichment, formatting, recommendation, daily briefing |
| Browser automation | Chrome Extension (Manifest V3) |
| AI | OpenRouter, LangChain |

## Running Locally

### Backend

```bash
uv run ai-job-hunter-backend              # FastAPI dashboard (default :8000)
```

### Background worker

```bash
uv run ai-job-hunter-worker
```

### Frontend

```bash
cd src/ai_job_hunter/dashboard/frontend
npm install
npm run dev                               # Vite dev server at :5173
```

### Chrome Extension

```bash
cd src/chrome-extension
npm install
npm run build
# Load src/chrome-extension/dist/ as unpacked extension in Chrome
```

### CLI

```bash
uv run ai-job-hunter --help
```

Useful commands:

```bash
uv run ai-job-hunter scrape
uv run ai-job-hunter sources list
uv run ai-job-hunter sources check example-company
uv run ai-job-hunter daily-briefing
uv run ai-job-hunter daily-briefing --refresh-only
uv run ai-job-hunter daily-briefing --send-now
```

## Configuration

Copy `.env.example` to `.env` and set the values you use locally.

Important keys:

- `DB_PATH`, `TURSO_URL`, `TURSO_AUTH_TOKEN`
- `REDIS_URL`
- `AGENT_MODEL` — fast/SLM for simple queries (default `openai/gpt-4o-mini`)
- `AGENT_STRONG_MODEL` — strong model for generation/analysis/long messages (default `openai/gpt-4o`)
- `DASHBOARD_CACHE_TTL_SHORT`, `DASHBOARD_CACHE_TTL_LONG`
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- `JOB_HUNTER_TIMEZONE`
- `OPENROUTER_API_KEY`
- `ENRICHMENT_MODEL`
- `DESCRIPTION_FORMAT_MODEL`
- `ARTIFACT_MODEL`

## Current Boundaries

- outbound recruiter messaging workflows are not built into the product yet
- smart manual-add parsing from pasted job-board URLs is still future work
- LLM enrichment and artifact generation still depend on external model latency; artifact generation streams progressively so the UI is non-blocking, but total wall-clock time is bounded by the model
