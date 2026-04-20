# Changelog

## 2026-04-19 — Insights Page Completion

### Changed
- **Profile Blockers**: gap chips now link to `/board?q=<skill>` for one-click drill-down into matching jobs.
- **Targeting Signals**: new sidebar card on Insights consumes `profileInsights` to surface target-more roles (linked to board search), reduce-focus roles, and suggested profile updates derived from the AI profile analysis.
- **Role family trends**: "Where replies are actually showing up" chart now renders live data from `conversion.by_role_family` with applied vs. reply bars per family — no longer a stub.
- **Board `?q=` param**: navigating to `/board?q=Azure` pre-populates the search field, so gap and targeting chip links land with the filter active. URL param takes priority over page cache.

### Verified
- `npm run build`
- Manual review of InsightsPage and BoardPage changes.

---

## 2026-04-19 — Worker Reliability, ATS Critique Error Fix, and Agent Smart Routing

### Fixed
- **Worker `load_dotenv`**: `worker.py` was loading the task queue module before env vars were read from `.env`, causing `REDIS_URL` to always be empty and the worker to fail at startup with "Redis task queue is not available". Added `load_dotenv()` before any module-level import that reads env.
- **ATS critique 503**: `HTTPException` was raised inside the `with _conn()` context block, which caused the `anyio` thread-pool to swallow it as a 500. Moved the raise outside the block so FastAPI handles it correctly and returns a structured 503 with the LLM error detail.

### Changed
- **Agent model routing**: `agent_gateway/legacy_chat.py` now routes to `AGENT_STRONG_MODEL` for generation, analysis, and long messages (>100 words or keyword trigger) and `AGENT_MODEL` for simple queries. `response_mode` reflects the chosen route as `"llm_strong"` or `"llm"`.

---

## 2026-04-17 — ATS Critique Loop and Real Agent Tool-Use

### Added
- **ATS critique endpoint**: `POST /api/jobs/{job_id}/artifacts/ats-critique` runs a structured LLM pass over the active resume and job description to flag ATS keyword gaps, missing signals, and rewrite suggestions.
- **Critique UI**: "Check ATS" button in `ArtifactEditor` opens an inline critique panel with keyword gaps, a rewrite suggestion, and a one-click "Apply revised resume" action that replaces the active artifact without leaving the editor.
- **Real tool-use agent**: agent `response_mode: "tool_agent"` routes through a LangChain ReAct agent (`agent_gateway/tool_agent.py`) with registered tools for job search, profile read, and queue management. Simple queries continue to use the fast deterministic path.

---

## 2026-04-15 — Streaming Artifact Generation

### Changed
- **Artifact streaming**: resume and cover letter generation now streams tokens to the frontend via SSE, eliminating the previous 10–25 s blocking wait and showing progressive output in `ArtifactEditor`.
- **Operation delta events**: artifact operations emit incremental `delta` events through `GET /api/operations/{id}/events` so the editor renders token-by-token without polling.

### Fixed
- Resolved the known gap: artifact generation is no longer synchronous from the frontend's perspective.

---

## 2026-04-15 — Story Bank, Semantic Ranking, and Grounded Artifact Generation

### Added
- **Story bank**: structured evidence store extracted from the candidate profile and base documents, used to ground resume and cover letter generation in real accomplishments instead of hallucinated filler.
- **Semantic ranking**: recommendation ranking now incorporates semantic similarity between role requirements and profile content, supplementing the numeric `rank_score`.
- **Grounded artifacts**: resume and cover letter LLM calls receive story-bank context in the system prompt, producing output anchored in real project impact data.

---

## 2026-04-14 — Apply Studio Correction

### Changed
- **Apply page direction**: Corrected the page away from a generic two-card split and rebuilt it as a calmer studio shell that better matches `.impeccable.md` and the Ethereal Navigator design intent.
- **Interaction hierarchy**: Made the left pane the dominant conversation workspace with a stronger editorial title block, compact current-task strip, command chips, slash-skill picker, and anchored composer.
- **Action canvas**: Reframed the right pane as a quieter output surface that persists the latest tangible result instead of competing with chat as an equal feature panel.
- **Visual language**: Reduced decorative chrome, improved asymmetry, tightened spacing rhythm, and reserved gradient emphasis for actual primary actions rather than using it as a generic page treatment.
- **Apply semantics**: The page now reads as `AI Co-pilot Studio` with slash-first workflows for `/discover`, `/resume`, `/cover-letter`, and `/critique`.

### Verified
- `npm.cmd run build`
- Live browser walkthrough on desktop and mobile for `/agent`
- Slash picker rendering verified in browser
- Browser console check returned `0` errors

---

## 2026-04-08 — Match Scoring Rebuild And Instant Dashboard Fast Path

### Changed
- **Scoring model**: Replaced the old saturated additive scorer with a two-stage system that separates `raw_fit`, cohort-calibrated `rank_score`, and stage-aware `recommendation`.
- **Recommendation semantics**: `fit_score` now follows raw fit, while list ordering and top-job surfacing use calibrated rank. This prevents most jobs from clustering near 100 and makes top bands meaningful again.
- **Product surfaces**: Updated Board, Recommend, Insights, detail views, queue surfaces, and agent copy to stop treating match score like a literal fit percentage.
- **Recommend page**: Skill-gap analysis now stays active against the current recommendation set and recommendation filters align with ranking semantics instead of the old pseudo-percent thresholds.
- **Fast read path**: Added snapshot-backed job projections and a bootstrap-first loading model so board, recommend, insights, and assistant reads no longer assemble everything live on every request.
- **Background work**: Artifact generation and snapshot refresh now route through queued workspace operations with a dedicated worker entrypoint instead of blocking request handlers.
- **Shared caching**: Added a shared frontend cache for bootstrap, jobs, queue, detail, events, and artifacts, replacing page-specific cache duplication on the board.
- **Live refresh**: Added dashboard-wide SSE invalidation plus operation SSE so queue, artifact, recommendation, and snapshot updates propagate back into the UI without full manual refreshes.
- **Agent responsiveness**: Common agent prompts now resolve from local deterministic context first, with LLM fallback reserved for the remaining freeform prompts.

### Added
- `GET /api/bootstrap` for first-paint dashboard hydration
- `GET /api/events/stream` for dashboard-wide live invalidation
- `GET /api/operations/{id}` and `GET /api/operations/{id}/events` for background-operation tracking
- `src/dashboard/backend/worker.py` as the dedicated worker entrypoint for queued background tasks

### Verified
- `npm run build`
- `uv run pytest tests/test_job_id_routes.py tests/test_profile_and_repository.py tests/test_advisor_recommendation.py tests/test_match_score.py`
- `uv run python -m py_compile src/dashboard/backend/main.py src/dashboard/backend/cache.py src/dashboard/backend/task_handlers.py`

---

## 2026-04-08 — Calm Premium Frontend Realignment

### Changed
- **Shell / IA**: Reframed the main frontend around clearer route roles in the app shell: `Today`, `Board`, `Discover`, `Apply`, `Strategy`, and `Settings`, while keeping route paths stable.
- **Shared design system**: Normalized cross-page rails, glass surfaces, tonal layering, mobile compression, and calmer utility controls to align the product more closely with `.impeccable.md`.
- **Today**: Rebuilt the page into a compact daily operating brief with a short briefing rail, must-do-now lane, follow-up lane, lower-urgency lane, and top signals area. Quiet states now provide clearer next-step guidance.
- **Insights -> Strategy**: Reworked the page away from KPI-dashboard composition into a strategy review surface centered on pipeline health, source performance, profile blockers, and course-correction notes.
- **Strategy visuals**: Restored quick-read visual analysis inside the calmer Strategy page with a tracked-pipeline donut and match-score distribution histogram, so the page again supports instant pattern recognition without reverting to a metrics wall.
- **Recommend -> Discover**: Narrowed the page into a curated intake queue for strong unopened roles. Reduced score theatrics, simplified cards, and made the page more clearly about triage into Board / Apply.
- **Agent -> Apply**: Reorganized the application workflow into a clearer studio model with queue context, working documents, readiness signals, and an embedded assistant rail.
- **Settings**: Redesigned the page into a calmer workspace and expanded it beyond contact info by adding visible search-preference editing for desired titles, target role families, and core skills.

### Verified
- `npm.cmd run build`
- Live browser walkthrough on desktop and mobile for `Today`, `Discover`, `Apply`, `Strategy`, and `Settings`
- Live browser walkthrough on desktop and mobile for the restored Strategy visuals
- Final browser console check returned `0` errors

---

## 2026-04-01 (Session 9) — Final Polish & Accessibility Pass

### Changed
- **Accessibility**: Added universal `prefers-reduced-motion` support, disabling all animations and transitions for users with motion sensitivities.
- **Focus Management**: Implemented a universal `:focus-visible` ring (2px accent outline) across all interactive elements, ensuring robust keyboard navigation and WCAG compliance.
- **Cross-Browser Styles**: Added `scrollbar-color` token support for Firefox, ensuring custom scrollbars render consistently across Chrome and Firefox.
- **Code Cleanup**: Extracted temporary inline styles from `DetailDrawer.tsx` into dedicated, semantic CSS classes (`fit-card--compact`, `fit-list--compact`).

---

## 2026-04-01 (Session 8) — Detail Drawer Density & Scanning

### Changed
- **High-Density Hero**: Redesigned the job detail header to consolidate Title, Status, Priority, and metadata into a compact, 2-column summary grid.
- **Analysis-First Layout**: Reordered the detail drawer to place AI Recommendation, Fit analysis, and Skill Alignment at the top, ensuring decision-support data is immediately visible.
- **Compact Fit Matrix**: Optimized the "Skill Alignment" section with a 2-column layout and reduced padding, significantly decreasing the vertical height of the drawer.
- **Responsive Fact Grid**: Converted technical enrichment facts into a 2-column grid, making it easier to scan salary, seniority, and work mode at a glance.
- **Micro-Copy Refinement**: Simplified action labels and placeholders within the pipeline control panel for better clarity.

---

## 2026-04-01 (Session 7) — Guided Onboarding & Empty States

### Added
- **Today Page Cold Start**: Implemented a "Ready to start your day?" onboarding card for users with no daily briefing, featuring a prominent "Generate First Briefing" action.
- **Board Page Global Empty State**: Added a "Your pipeline is empty" illustration and CTA for users who haven't tracked any jobs yet, guiding them to add a job or check recommendations.
- **Actionable Column States**: Updated all Kanban column empty states with descriptive copy that explains the specific role of each stage (Staging, Applied, Interviewing, etc.) and how to move jobs into them.

### Changed
- **Styling**: Added modern, gradient-based layouts for onboarding cards in `styles.css`.
- **Refinement**: Simplified initial user experience by hiding complex grid layouts when no data is present, replacing them with clear, single-action surfaces.

---

## 2026-04-01 (Session 6) — Cross-Platform Adaptation

### Added
- **Mobile Navigation**: Implemented a fixed **Bottom Navigation Bar** for mobile devices (< 760px), providing quick access to primary dashboard pages (Today, Board, Insights, Recommend, Agent).
- **Mobile Top Bar**: Added a sticky header for mobile with the brand identity and user avatar.
- **Kanban Column Switcher**: Implemented a tab-based column selector for the Kanban board on mobile, allowing users to focus on one stage at a time without horizontal overflow issues.

### Changed
- **Responsive Layout**: Overhauled the app shell to use fixed sidebar on desktop and bottom nav on mobile. Optimized content margins and padding for all screen sizes.
- **Detail Drawer Adaptation**: The Detail Drawer now expands to **full-screen** on mobile for better focus and readability of job facts.
- **Touch Targets**: Increased interactive area for buttons and navigation links on touch devices (44px minimum height).
- **Dynamic FAB Positioning**: Adjusted the AI Orb FAB position to sit above the bottom nav on mobile.
- **Typography Scaling**: Refined heading sizes and metric typography for smaller viewports.

---

## 2026-04-01 (Session 5) — Typography Refinement

### Added
- **Design Context**: Established formal design context in `.impeccable.md` focusing on "The Navigator" brand personality (Authoritative, Calm, Disciplined).
- **Typography System**: Implemented a comprehensive typography system in `styles.css` using:
  - **Headings**: "Plus Jakarta Sans" (Geometric, distinctive).
  - **Body**: "Inter" (Readable, neutral).
  - **Modular Scale**: 1.2 ratio scale (`--fs-xs` to `--fs-3xl`).
  - **Semantic Tokens**: Dedicated tokens for font weights (`--fw-*`), line heights (`--lh-*`), and letter spacing (`--ls-*`).

### Changed
- **Visual Hierarchy**: Refined all major surfaces (Today, Board, Insights, Recommend, Detail Drawer) to use the new type system, ensuring clear distinction between display text, headings, and functional UI labels.
- **Readability**: Optimized line heights (1.6 for body, 1.25 for headings) and established `max-width: 70ch` for long-form content like job descriptions.
- **Chrome Extension Alignment**: Updated the Chrome extension popup and sidepanel to match the dashboard's new typography for a cohesive cross-surface experience.
- **Tabular Data**: Applied `tabular-nums` to all counts, metrics, and KPI values for stable visual alignment.

---

## 2026-04-01 (Session 4) — High-Performance Caching

### Fixed
- **Instant Tab Switching**: Implemented `DashboardDataContext` in the frontend to persist core metadata (Stats, Profile, Insights) across page navigations, eliminating repeated loading spinners.
- **Redundant Network Requests**: Centralized dashboard data fetching into a single global provider, reducing API calls by ~70% when browsing the dashboard.

### Changed
- **Intelligent Browser Caching**: Updated backend `Cache-Control` to `private, max-age=60, stale-while-revalidate=30`, allowing the browser to serve instant cached responses while validating in the background.
- **Enabled Profile Caching**: Removed `no-store` from `/api/profile` and enabled Redis + Browser caching for candidate profiles and metadata.
- **Refactored Pages**: `TodayPage`, `InsightsPage`, and `RecommendPage` now use the shared context for a smoother, "app-like" experience.

### Added
- **Stale-While-Revalidate Pattern**: Frontend now supports background data refreshes without UI blocking.
- **Dashboard Data Context**: New `DashboardDataContext.tsx` for global state management.

---

## 2026-04-01 (Session 3) — Stability & Architectural Cleanup

### Fixed
- **Turso 500 Errors**: Added context manager support (`__enter__`/`__exit__`) to `_TursoConnection` in `src/db.py`, fixing crashes on Application Workflow endpoints.
- **Database Initialization**: Ensured `init_db()` creates Application Workflow tables (`application_queue`, `base_documents`, `job_artifacts`) on Turso.
- **Conversion Metrics**: Insights funnel and charts now correctly count tracking statuses as implicit outcomes, preventing "0%" metrics for applied/interviewing jobs.
- **Skill Normalization Duplication**: Centralized skill alias table in `src/match_score.py` and exposed via new `GET /api/meta/skill-aliases` endpoint. Refactored `advisor.py` and `DetailDrawer.tsx` to use this single source of truth.

### Added
- **Shared Utils**: Created `src/dashboard/backend/utils.py` to house shared logic like `.env` loading, timezone helpers, and DB connection management.
- **Skill Aliases Endpoint**: `GET /api/meta/skill-aliases` for frontend-backend alignment.

### Changed
- **UX Refinement**: Moved the **Timeline** section in `DetailDrawer.tsx` above the Job Description to reduce scrolling for active applications.
- **Architectural Cleanup**: Deduplicated helper functions across `main.py` and `repository.py` while maintaining test compatibility.

---

## 2026-04-01 (Session 2) — Dashboard UX Refinement: Sidebar Collapse, Kanban Layout, Insights Charts, Compact Sort

### Added

#### Sidebar Collapse / Expand Toggle
- Collapsible left sidebar with toggle button (bottom-right corner) — transitions between 256px (expanded) and 64px (collapsed)
- Smooth CSS transitions with chevron icons (ChevronLeft/ChevronRight from lucide-react)
- Collapse state persisted in `localStorage` under key `SIDEBAR_COLLAPSED_KEY`
- Applied `.sidebar-collapsed` class on `.app-shell` to adjust layout, content margins, and label visibility
- All nav links remain accessible; labels hidden when collapsed

#### Top Nav Removal & Sidebar Bottom Consolidation
- Removed entire floating top nav (`<nav className="top-nav">` ~140 lines CSS)
- Moved **Theme Toggle** (`ThemeToggle`) and **Avatar** to sidebar bottom (new `.side-nav-bottom` section)
- Theme toggle keyboard shortcut (K) still active
- Cleaner, less cluttered header area on main content pages

#### Insights Page Complete Visual Redesign
- Replaced raw numbers with interactive visualizations powered by SVG and responsive layouts
- **KPI Cards** — metric displays (Tracked Jobs, Active Pipeline, Avg Match Score, Response Rate) with optional accent styling
- **Conversion Funnel** — visual waterfall showing Staging → Applied → Interviewing → Offer → Rejected with conversion rates between stages
- **Score Histogram** — 5-bin distribution chart (0-19, 20-39, 40-59, 60-79, 80-100) with color-coded bars and counts
- **Pipeline Donut Chart** — SVG donut with color legend showing breakdown by stage (Staging/Applied/Interviewing/Offer/Rejected)
- **Skill Gap Analysis** — lists top 5 missing skills from profile matches, no visual if profile complete
- **Role Family Performance** — placeholder section ready for role family trend data
- **AI Strategy Coach Card** — calls `/api/agent/chat` with rich context (conversion rates, pipeline status, skill gaps, source quality) and displays LLM-generated strategy recommendations with "Generate Insights" button
- Loading state with spinner while data is fetched; AI Coach loads asynchronously after initial data
- Full-width responsive grid layout with stacked cards on mobile

#### ColumnSortButton Component (Compact Sort Buttons)
- New component `src/components/ColumnSortButton.tsx` — replaces the old full-width `ThemedSelect` dropdown on kanban column headers
- **Design**: 28×28px button with up/down chevron icon (ChevronDown when closed, ChevronUp when open)
- **Interaction**: Radix UI popover (`@radix-ui/react-popover`) opens menu with 5 sort options
- **Menu Options**: Stage priority (default), Best match, Newest posted, Recently updated, Company A-Z
- **Active Indicator**: Selected option marked with checkmark (✓) and accent color highlight
- **Styling**: Minimal gray border, light background, subtle hover effects, smooth slide-up animation (120ms ease-out)
- Removed column count badge (`.column-count` CSS removed)
- Type `ColumnSortOption` exported from `src/types.ts` for reusability

#### Kanban Board: Full-Page Scrolling (No Column-Wise Scroll)
- Changed `.kanban-column` from fixed height (`calc(100vh - 340px)`) with `overflow: hidden` to `height: auto` and `overflow: visible`
- Changed `.column-items` from `flex: 1 1 auto` with `overflow-y: auto` to `flex: 0 1 auto` with `overflow: visible`
- Columns now grow naturally based on card count; entire page scrolls instead of individual columns
- Horizontal scroll still available on narrow screens for all columns together
- Cleaner, unified scrolling experience

#### FAB Visibility Route Filtering
- AI Orb FAB now hidden on `/board` and `/agent` pages (those pages don't need it)
- FAB visible on: `/today`, `/insights`, `/recommend`, `/settings`
- Implemented via `location.pathname` conditional in App.tsx

### Fixed

- **Browse controls auto-open**: Verified `useState(false)` on BoardPage (already fixed in previous session)
- **Kanban columns not fitting**: 5 columns now sized at ~267px each with responsive grid (`grid-template-columns: repeat(5, minmax(200px, 1fr))`)
- **Column sort overlap**: Replaced full-width ThemedSelect dropdown with compact 28px button
- **Viewport height calculations**: Removed fixed height constraints; layout now flows naturally

### Changed

- **Board Layout**: Columns display in `display: grid` with 5 equal-width slots; no individual column height locks
- **Insights page structure**: Modularized into sub-components (`KpiCard`, `HBar`, `FunnelChart`, `ScoreHistogram`, `PipelineDonut`, `AICoachCard`) for maintainability
- **Sort UX**: Kanban column sort is now an icon-button popover instead of a inline dropdown

### Dependencies Added

- `@radix-ui/react-popover@^1.1.15` — for ColumnSortButton popover menu

---

## 2026-04-01 (Session 1) — Ethereal Navigator redesign, Application Workflow, Chrome Side Panel, SmartRecruiters

### Added

#### "Ethereal Navigator" Design System
Full visual redesign of the dashboard based on the "Ethereal Navigator" design system (see `.impeccable.md` for the full design context). Key principles: spatial UI, glassmorphism, tonal layering instead of hard borders.

- **Floating glassmorphic top nav** — fixed, `left: 12px; right: 12px`, 18px border-radius, `rgba(255,255,255,0.72)` with `backdrop-filter: blur(24px)`, always fits within viewport
- **Left sidebar** (`side-nav`) — fixed 256px, displayed at ≥1024px, slides in as overlay on mobile via hamburger. Contains "The Navigator" AI identity block (gradient orb + badge) and all 6 nav links with active highlight
- **AI Orb FAB** — fixed bottom-right, gradient `#630ed4 → #0058be`, glows on hover
- **New design tokens** — full `:root` palette overhaul: `--page-bg: #f6fafe`, `--surface-0..3`, `--accent: #630ed4`, `--secondary: #0058be`, `--tertiary`, border tokens, radius tokens up to `--radius-2xl: 24px`. Dark mode counterparts
- **Utility classes**: `.glass-card`, `.ai-gradient`, `.orb-glow`, `.ambient-shadow`
- **Responsive layout guards** — `overflow-x: hidden` on `.app-shell` and `.app-shell-content`, explicit `width: calc(100% - 256px)` at 1024px+, `min-width: 0; max-width: 100%` on all page containers and grid children

#### Recommend Page v2 (`/recommend`)
Complete rewrite with bento grid layout matching the `assets/recommended_page.html` mockup.

- **Editorial hero header** — contextual greeting ("I've found X ML Engineer opportunities for you"), kicker label, lede copy, inline filter strip (score threshold pills, ATS dropdown, title-match toggle, count badge)
- **Bento grid** — single column on mobile, `minmax(0,8fr) minmax(0,4fr)` at ≥1200px
- **`RecommendJobCard` v2** — full glass card rewrite: decorative gradient blob, company letter-avatar, SVG circular score ring (stroke-dasharray arc, green/violet/amber by score), skill chips (matched=green, gap=amber), AI Reasoning section (guidance_summary with frosted violet tint), `+ Queue` and `View →` pill buttons
- **Skill Gap Analysis sidebar** — derives top 5 required skills from top-5 jobs, cross-references against profile skills, renders color-coded progress bars (green/violet/amber by match %)
- **AI Resume Coach sidebar** — gradient card linking to the Agent page with context about the top matching job
- **Backlog-only filter** — only `not_applied` jobs shown; applied, staging, interviewing, offer, and rejected jobs are excluded

#### Application Workflow (Backend + Frontend)
Full end-to-end pipeline for tailoring and managing job applications.

**Backend (`src/db.py`, `src/dashboard/backend/artifacts.py`, `src/dashboard/backend/main.py`, `src/dashboard/backend/schemas.py`):**
- 3 new DB tables: `base_documents` (source resumes/cover letters), `application_queue` (queued jobs with status), `job_artifacts` (AI-tailored docs, versioned)
- `src/dashboard/backend/artifacts.py` — new module: file parsing (PDF via pdfplumber, DOCX via python-docx, plain text), queue CRUD, artifact CRUD with auto-archiving of previous versions, LLM generation (`generate_tailored_resume`, `generate_cover_letter` via OpenRouter), PDF export via fpdf2+markdown2, URL normalization + lookup for Chrome extension
- 14 new API endpoints: base document CRUD + default, queue CRUD + reorder, job artifacts list/generate/update, artifact PDF download, `GET /api/artifacts/by-url`
- New Pydantic schemas: `BaseDocument`, `QueueItem`, `JobArtifact`, `GenerateArtifactRequest`, `UpdateArtifactRequest`, `AddToQueueRequest`, `UpdateQueueItemRequest`, `ReorderQueueRequest`, `ArtifactsByUrlResponse`

**Frontend:**
- **Settings page** (`/settings`) — personal info form (full_name, email, phone, linkedin_url, portfolio_url, city, country) + base document management (upload PDF/DOCX/txt/md, list with set-default and delete, collapsible markdown preview)
- **Agent page rewrite** (`/agent`) — 55/45 split (stacked on mobile, grid at ≥900px): left pane is the Application Workflow (queue list, job picker modal, working-on section with ArtifactEditor for resume + cover letter); right pane is the existing chat assistant
- **`ArtifactEditor` component** — Edit/Preview tabs, textarea with monospace font, ReactMarkdown preview, Generate + Download PDF buttons, Save with "Saved ✓" / "Unsaved changes •" status indicator
- **"Add to Queue" button** in `DetailDrawer` action row (between Stage and Pin)
- **"+ Queue" button** in `RecommendJobCard`
- New TypeScript types: `BaseDocument`, `QueueItem`, `JobArtifact`
- New API functions: all queue, base document, and artifact operations

#### Chrome Extension — Side Panel + SmartRecruiters + File Upload

**Side Panel:**
- `src/chrome-extension/src/sidepanel/sidepanel.html` + `SidePanel.tsx` + `sidepanel.css` — full-height side panel that auto-opens on supported ATS pages. Shows job info (title, company, location matched by URL), Resume / Cover Letter tabs with `marked.js` markdown preview, Autofill + Upload Files button
- `manifest.json` updated: `"sidePanel"` permission, `"side_panel": { "default_path": "..." }` config
- `src/background.ts` — auto-opens side panel via `chrome.sidePanel.open({ tabId })` when navigating to Greenhouse/Lever/Ashby/Workable/SmartRecruiters ATS pages; handles `SIDEPANEL_AUTOFILL` message type alongside existing `AUTOFILL_PAGE`

**SmartRecruiters ATS module:**
- `src/chrome-extension/src/content/smartrecruiters.ts` — detects `input[name="firstName"]` or `[data-testid="apply-form"]`; fills firstName, lastName, email, phone, LinkedIn, location; falls back to `genericFill`
- SmartRecruiters URL patterns added to `manifest.json` host permissions and content script matches

**File upload:**
- `uploadArtifactToFileInput(artifactId, type)` in `utils.ts` — fetches artifact PDF from `/api/artifacts/{id}/pdf`, injects into `<input type="file">` via DataTransfer API, dispatches `change`/`input` events. No download dialog shown.
- `findFileInput(type)` — searches by name/id/accept attribute keywords, falls back to first file input on page
- `DO_AUTOFILL` handler updated to upload resume and cover letter PDFs when artifact IDs are provided

**Extension API:**
- `getArtifactsByUrl(url)` — calls `GET /api/artifacts/by-url`, returns `ArtifactsByUrlResponse` with job_info, resume, cover_letter
- New interfaces: `ArtifactInfo`, `ArtifactsByUrlResponse`

### Changed

#### Navigation (`App.tsx`)
- Removed Radix `NavigationMenu`, `LayoutGroup`, `VisuallyHidden` — replaced with plain semantic HTML using new CSS classes
- Top nav shows brand + active page label (mobile) + theme toggle + avatar + hamburger
- Sidebar shows AI identity block + 6 nav links (Today, Board, Insights, Recommend, Agent, Settings)
- `/settings` route added

#### Recommend Page filtering
- Only `not_applied` jobs shown — staging, applied, interviewing, offer, and rejected are excluded at filter time
- "Mark Applied" button removed from recommend cards (action belongs on Board)

### Dependencies added

**Python:**
- `pdfplumber` — PDF text extraction
- `python-docx` — DOCX text extraction
- `fpdf2` — PDF generation from markdown
- `markdown2` — Markdown to HTML (used by fpdf2)

**Dashboard frontend:**
- `react-markdown`, `remark-gfm` — markdown preview in ArtifactEditor

**Chrome extension:**
- `marked` — lightweight markdown-to-HTML for side panel preview

### New environment variable
- `ARTIFACT_MODEL` — model for resume/cover letter generation (default: `openai/gpt-4o`)

---

## 2026-04-01 — Jobright-inspired redesign, Recommendations, AI Agent, Chrome Extension

### Added

#### Chrome Extension (`src/chrome-extension/`)
A full Manifest V3 Chrome extension for auto-filling job application forms, built with Vite + `@crxjs/vite-plugin` + React + TypeScript. Has its own `package.json` and is built independently with `npm run build` inside `src/chrome-extension/`. The output goes to `src/chrome-extension/dist/` and is loaded as an unpacked extension in Chrome.

**Architecture:**
- `manifest.json` — Manifest V3 with `storage`, `activeTab`, `scripting` permissions. Content scripts are injected only on known ATS job application page URL patterns (Greenhouse, Lever, Ashby, Workable). Service worker in `src/background.ts`.
- `src/api.ts` — Dashboard API client with configurable base URL stored in `chrome.storage.sync` (key: `dashboardUrl`, default: `http://127.0.0.1:8000`). Exports: `getDashboardUrl`, `setDashboardUrl`, `checkHealth` (3s timeout), `fetchAutofillProfile` (5s timeout), `getCachedProfile` (session-scoped 5-min cache via `chrome.storage.session`), `clearProfileCache`. The `AutofillProfile` interface maps to the backend's `/api/profile/autofill-export` response.
- `src/background.ts` — Service worker. Listens for `AUTOFILL_PAGE` messages from the popup; finds the active tab and forwards a `DO_AUTOFILL` message to the tab's content script; relays the response back to the popup.
- `src/content/index.ts` — Content script entry point. Runs `detectModule()` (tries greenhouse → lever → ashby → workable → generic in order). Listens for `DO_AUTOFILL`, fetches the cached profile, calls `mod.fillForm(profile)`, returns `{ ok, filled, fields }`. On load, injects a purple "AJH Autofill ready" toast badge in the bottom-right corner for 3 seconds (only if a non-generic ATS is detected, or if generic detects a valid form).
- `src/content/types.ts` — `FillResult { filled: number; skipped: number; fields: string[] }`.
- `src/content/utils.ts` — `fillField(el, value)`: uses native React property setter (`Object.getOwnPropertyDescriptor`) + dispatches `input`, `change`, `blur` events to trigger React/Vue reactivity. `findInputByLabelText(text)`: finds `<label>` by case-insensitive text, returns the associated input via `htmlFor`, child query, or next sibling. `genericFill(profile)`: maps keyword arrays to profile fields and fills all unmatched inputs.
- `src/content/greenhouse.ts` — Fills `input[name="job_application[first_name]"]`, `[last_name]`, `[email]`, `[phone]`, `[linkedin_profile]`, `[website]`. `detectForm()` checks for presence of `input[name^="job_application"]`.
- `src/content/lever.ts` — Fills `[data-qa="name"]`, `[data-qa="email"]`, `[data-qa="phone"]`, `[data-qa="org"]`. `detectForm()` checks for `[data-qa="name"]`.
- `src/content/ashby.ts` — Label-text matching via `findInputByLabelText` for First Name, Last Name, Email, Phone, LinkedIn URL, Location. `detectForm()` checks for `.ashby-application-form` or `[data-testid="application-form"]`.
- `src/content/workable.ts` — Fills `input[name="firstname"]`, `[name="lastname"]`, `[name="email"]`, `[name="phone"]`, `[name="address"]`. `detectForm()` checks for `input[name="firstname"]`.
- `src/content/generic.ts` — Heuristic fallback using `genericFill()` from utils. `detectForm()` detects any `<form>` with ≥3 labeled inputs.

**Popup UI (`src/popup/Popup.tsx` + `popup.css`):**
Originally plain inline-style React component. Redesigned (2026-04-01) to be Jobright-inspired:
- 340px wide with purple→indigo gradient header (`#6d28d9` → `#4f46e5`)
- AJH logo tile with frosted-glass border in header
- `status-badge` with animated pulsing green dot when connected
- Gear icon (inline SVG) toggles a `settings-panel` that slides in below the header for URL editing
- `ProfileCard` — shows avatar with initials (from `first_name`/`last_name`/`full_name`), display name, email, and a pill counter showing `X/6` ready fields
- `FieldGrid` — 2-column grid of 6 field chips (First Name, Last Name, Email, Phone, LinkedIn, Location): green ✓ chips for fields with data, gray — chips for missing fields
- Loading state: 3 bouncing dots animated via CSS while `status === "checking"`
- Empty states for disconnected (shows backend URL) and no-profile (links user to dashboard)
- Fill result card: green on success (shows count + field names), red on error
- Autofill button: gradient with box-shadow, lifts on hover (`translateY(-1px)`) with increased shadow, spinner animation while filling, disabled at 45% opacity when not connected
- All styles in `popup.css` using Inter from Google Fonts

#### Recommendations Page (`/recommend`)
- `src/dashboard/frontend/src/pages/RecommendPage.tsx` — Fetches up to 200 jobs sorted by `match_desc` and the candidate profile. Filters by score threshold (60/70/80 slider), ATS type, and title-match toggle. Clicking a job fetches its `JobDetail` and `JobEvent[]`, passes them into `DetailDrawer` (same component used by Board). On tracking changes, re-fetches the job detail.
- `src/dashboard/frontend/src/components/RecommendJobCard.tsx` — Landscape card showing: company + title + location/ATS/posted metadata, a score circle (`.recommend-score-circle` with `score-high`/`score-medium`/`score-low`/`score-pending` CSS classes), top-3 required skills as `skill-chip--matched` (green) or `skill-chip--gap` (red/orange) chips based on profile skills comparison, recommendation badge, "View" button.

#### AI Agent Page (`/agent`)
- `src/dashboard/frontend/src/pages/AgentPage.tsx` — Conversational chat interface. Shows 4 suggested-prompt chips when the thread is empty ("What should I apply to today?", "Which jobs match my skills best?", "Where am I losing momentum?", "What skills should I add to my profile?"). `send(text)` appends the user message to state, calls `agentChat(messages)`, appends the assistant reply. Shows animated thinking dots while awaiting response. Textarea auto-resizes; Enter sends, Shift+Enter inserts newline.
- `src/dashboard/backend/agent.py` — `build_agent_context(conn)` queries status counts, top-5 highest-match not-applied jobs, overdue staging jobs, and profile summary (years experience, skill count, desired titles). Injects this snapshot as the system prompt context. `handle_agent_chat(messages, conn)` creates a `langchain_openai.ChatOpenAI` instance pointing at `https://openrouter.ai/api/v1` with model from `AGENT_MODEL` env var (default `openai/gpt-4o-mini`), temp=0.4, max_tokens=1200. Each call rebuilds the context fresh (no caching). Returns `{ reply, context_snapshot }`.

#### New backend endpoints
- `GET /api/profile/autofill-export` — Returns a flat profile object with `first_name` and `last_name` split from `full_name` (splits on first space). Used by the Chrome extension. CORS allows `chrome-extension://*` origins.
- `POST /api/agent/chat` — Accepts `{ messages: [{ role, content }] }`, returns `{ reply, context_snapshot }`. No Redis caching. Uses `handle_agent_chat` from `agent.py`.

### Changed

#### Backend schema and DB (`src/db.py`, `src/dashboard/backend/schemas.py`, `src/dashboard/backend/repository.py`)
- `candidate_profile` table: 7 new columns added via `ALTER TABLE ... ADD COLUMN` (auto-migrating): `full_name TEXT`, `email TEXT`, `phone TEXT`, `linkedin_url TEXT`, `portfolio_url TEXT`, `city TEXT`, `country TEXT DEFAULT 'Canada'`.
- `get_candidate_profile()` and `upsert_candidate_profile()` in `db.py` updated to read/write all 7 new fields.
- `CandidateProfile` Pydantic schema extended with all 7 new optional fields (`str | None`).
- `JobSummary` schema: added `required_skills: list[str] = Field(default_factory=list)`.
- `list_jobs()` in `repository.py`: before popping the enrichment dict, extracts `item["required_skills"] = (item.get("enrichment") or {}).get("required_skills", [])[:5]` (first 5 skills for card display).
- New schemas: `AgentMessage { role, content }`, `AgentChatRequest { messages }`, `AgentChatResponse { reply, context_snapshot }`.

#### Frontend types and API (`src/dashboard/frontend/src/types.ts`, `src/dashboard/frontend/src/api.ts`)
- `JobSummary`: added `required_skills: string[]`.
- `CandidateProfile`: added `full_name`, `email`, `phone`, `linkedin_url`, `portfolio_url`, `city`, `country`.
- New interfaces: `AgentMessage`, `AgentChatRequest`, `AgentChatResponse`.
- `agentChat(messages)` function added to `api.ts`.

#### Navigation (`src/dashboard/frontend/src/App.tsx`)
- Nav now has 5 items with lucide-react icons: Today (`Home`), Board (`LayoutDashboard`), Insights (`BarChart2`), Recommend (`Sparkles`), Agent (`Bot`).
- Two new routes: `/recommend` → `<RecommendPage />`, `/agent` → `<AgentPage />`.
- Icons rendered as `<item.icon size={15} className="app-shell-nav-link-icon" aria-hidden="true" />`.

#### CORS (`src/dashboard/backend/main.py`)
- `allow_origin_regex` updated to: `r"^(https?://(localhost|127\.0\.0\.1|host\.docker\.internal)(:\d+)?|chrome-extension://.*)$"`

### Fixed (code review items)
- **Favicon**: `src/dashboard/frontend/public/favicon.svg` added (purple SVG monogram), linked in `index.html`.
- **Today page empty state**: "Preparing today's briefing..." replaced with "No briefing yet — generate one to see today's priorities." Added "Generate Briefing" button that calls `refreshDailyBriefing()`.
- **Board page Browse controls**: `isBrowsePanelOpen` initial state changed from `false` to `true` (expanded by default).
- **Detail drawer duplicate Archive chip**: Removed the `assistant-recommendation-chip` from the `detail-block-head` in the Recommendation section (it also appears in the action row, so it was duplicate).
- **Detail drawer close button**: Both instances changed from `data-icon="×">Close</Button>` to `aria-label="Close" data-icon="×">×</Button>` — no redundant text label.
- **JobCard pin badge**: `📌` emoji replaced with `<span className="job-pin-badge">Pinned</span>` text badge.
- **JobCard skill chips**: First 3 `required_skills` rendered as `<span className="skill-chip">` in the card footer.
- **BoardPage `detailToSummary()`**: Added `required_skills: detail.enrichment?.required_skills ?? []` to fix TypeScript compile error after `required_skills` was added to `JobSummary`.

---

## 2026-03-30

### Changed
- Simplified the manual-add modal so it now behaves like a compact form instead of a feature explainer.
- Required fields are now marked directly in the form, with lightweight validation and invalid highlighting on save attempt.
- Duplicate-aware manual add now uses concise messaging and reopens the existing record without extra explanatory banners or footer copy.

### Fixed
- Hardened assistant-surface cache invalidation so `Today` and `Insights` stay fresh after tracking changes, events, suppress/unsuppress, decisions, deletes, and action updates.
- Cleaned up later-stage recommendation wording so `applied`, `interviewing`, and `offer` jobs no longer fall back to early-stage “fit is weak” style reasoning.
- Verified the retry-processing drawer flow end to end with a real failed-processing state and retry transition.

### Docs
- Refreshed `README.md`, `CHANGELOG.md`, and `TODO.md` to match the current dashboard structure, processing model, caching behavior, and backlog status.

## 2026-03-29

### Added
- Durable job processing state with `processing`, `ready`, and `failed` states visible in the dashboard.
- Retry-processing API and drawer retry action for failed background enrichment / formatting / recommendation work.
- Redis + `ETag` cache parity for `Today`, daily briefing, action queue, conversion, source quality, profile gaps, and profile insights.
- Stage-aware recommendation presentation fields for narrative later-stage guidance.

### Changed
- `Today` was reworked into an operational landing page organized around `Must do today`, `Follow up today`, `Review later`, and `Top notes`.
- Manual add now opens instantly while background processing runs asynchronously.
- Manual add now prevents duplicates by exact URL and by normalized title + company + location + posted-month matching.
- Job descriptions are normalized before persistence and before enrichment sees the text.
- Clicking outside the drawer now closes it consistently on desktop and mobile.

### Removed
- Application-brief UI and API surface from the active dashboard product flow.

## 2026-03-28

### Added
- Interview-focused advisor layer with interview-likelihood scoring, recommendation reasons, manual decision overrides, action queue persistence, outcome analytics, and profile-gap insights.
- Daily briefing system with:
  - persisted one-row-per-day briefing state
  - dashboard Daily Briefing panel
  - Telegram daily briefing formatter and send path
  - same-day Telegram send dedupe
  - CLI entrypoint: `uv run python src/cli.py daily-briefing`

### Changed
- Workspace scrape, enrich, and JD reformat flows now refresh the stored daily briefing after successful runs.
- Dashboard is now split into `Today`, `Board`, and `Insights`, with assistant and analytics surfaces moved off the Kanban page.
- Board drawer keeps the core evaluation workflow but is reordered for easier scanning, with timeline and cleanup actions pushed to the bottom.
- `.env.example` now documents `JOB_HUNTER_TIMEZONE` for local-day briefing generation and Telegram dedupe.

### Notes
- The daily briefing is sourced from the same recommendation, action, and profile analytics already shown in the dashboard, so Telegram and the board use the same canonical payload.
- Scheduling remains external to the backend process; the repo provides the CLI command and a scheduler-friendly interface rather than an in-process scheduler.
