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
| “Interesting” and “active pipeline” blurred together | Good opportunities were not getting structured attention |
| There was no daily operating view | The search felt reactive instead of intentional |

AI Job Hunter is my attempt to solve that like a systems problem, not just a note-taking problem.

## What I Built

The product combines sourcing, workflow management, and assistant-style prioritization into one system.

<table>
  <tr>
    <td valign="top" width="33%">

### Today

The daily operating surface.

- daily briefing
- action queue
- follow-ups due
- concise next-step notes

Built to answer:

- what should I do today?
- which jobs need action now?

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

The longer-horizon review page.

- conversion metrics
- source quality
- profile-gap analysis
- targeting guidance

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

- early-stage jobs use opportunity evaluation
- later-stage jobs use active-process guidance
- the UI avoids misleading “interview likelihood” framing for jobs already in progress

### Performance model

The dashboard uses layered caching:

- browser memory reuse
- `ETag`-based HTTP revalidation
- Redis-backed server-side caching for board and assistant reads

## Stack

| Layer | Tools |
| --- | --- |
| Frontend | React, Vite, TypeScript |
| Backend | Python |
| Data / storage | SQLite or Turso |
| Cache | Redis |
| Workflow | scraping, enrichment, formatting, recommendation, daily briefing |

## Running Locally

### Backend

```bash
uv run python src/dashboard/backend/main.py
```

### Frontend

```bash
cd src/dashboard/frontend
npm install
npm run dev
```

### CLI

```bash
uv run python src/cli.py --help
```

Useful commands:

```bash
uv run python src/cli.py scrape
uv run python src/cli.py sources list
uv run python src/cli.py sources check example-company
uv run python src/cli.py daily-briefing
uv run python src/cli.py daily-briefing --refresh-only
uv run python src/cli.py daily-briefing --send-now
```

## Configuration

Copy `.env.example` to `.env` and set the values you use locally.

Important keys:

- `DB_PATH`, `TURSO_URL`, `TURSO_AUTH_TOKEN`
- `REDIS_URL`
- `DASHBOARD_CACHE_TTL_JOBS_LIST`
- `DASHBOARD_CACHE_TTL_JOB_DETAIL`
- `DASHBOARD_CACHE_TTL_EVENTS`
- `DASHBOARD_CACHE_TTL_STATS`
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
- `JOB_HUNTER_TIMEZONE`
- `OPENROUTER_API_KEY`
- `ENRICHMENT_MODEL`
- `DESCRIPTION_FORMAT_MODEL`

## Current Boundaries

- resume tailoring and cover-letter generation are intentionally not part of this README story yet
- outbound recruiter messaging workflows are not built into the product yet
- smart manual-add parsing from pasted job-board URLs is still future work
