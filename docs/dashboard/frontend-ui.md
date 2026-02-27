# Dashboard Frontend UI

The frontend is a kanban-first dashboard with a professional, Himalayas-inspired visual direction and dual dark/light theme support.

## Stack and entrypoints

- Path: `src/dashboard/frontend/`
- Tooling: Vite + React + TypeScript
- Routing: `react-router-dom`
- Animation library: `framer-motion`
- Visual polish components: ReactBits-style spotlight + shimmer tags
- Bootstrapping:
  - `src/main.tsx`
  - `src/App.tsx`

## Route layout

- `/` (`Board`): metrics strip + kanban + right detail drawer.
- `/profile` (`Profile`): dedicated profile editor for match scoring inputs.
- `/analytics` (`Analytics`): funnel conversion dashboard with date presets and conversion breakdown.
- Shared shell: left side rail navigation, mobile nav toggle, and theme switch.

## UX interactions

- Drag cards between columns to update status.
- Click a card to open side detail drawer.
- Job cards show score badge (`Match N (band)`).
- Edit tracking metadata inline (`status`, `priority`, `applied_at`, `next_step`, `target_compensation`).
- Edit profile on `/profile` and manually save to recompute/rerank scores.
- Delete a job from the detail drawer (`Danger Zone`), including linked tracking/events/enrichment rows via backend API.
- Status drag/drop and tracking edits persist through backend tracking patch API.
- Theme toggle switches between dark/light and stores preference in browser.
- Animated board column reveal on first render.
- Drop-target highlight while a card is dragged over a column.
- Spotlight-hover effect on top metric cards.
- Analytics page supports:
  - quick windows (`30d`, `90d`, `all`)
  - stage count cards
  - conversion-rate summary
  - conversion deltas vs previous equal window
  - weekly goals (applications + interview activity) with progress bars
  - actionable alert cards for stale pipeline states
  - cohort funnel table by posted week
  - source-quality ranking cards (ATS + companies)
  - click-through drill-down from cohort/source rows to pre-filtered Board view
  - forecast simulator:
    - scenario input (`forecast apps/wk`)
    - projected interviews/offers for next `7d` and `30d`
    - confidence-aware low/high bands
  - backend-backed refresh
- Smooth 200ms theme transition (disabled with `prefers-reduced-motion`).
- Board route keeps in-memory state cache for fast return navigation (`Board -> Profile -> Board`) without immediate refetch.
- Detail drawer uses background prefetch and cache reuse for job detail + timeline where available.

## Board controls & scroll behavior

- A single **Controls** capsule now reveals view/sort/filter/search controls without forcing the toolbar taller; the filter popover stays anchored to the capsule and exposes status/ATS/company/date range fields plus apply/clear actions.
- Active filters display an inline badge on the Controls capsule, and the control panel itself is configured to close when clicking outside so the toolbar stays tidy.
- Kanban action buttons (`Suppressed`, `Add Job`, `Refresh`) keep a fixed width, consistent spacing, and hover styling to match the Himalayas polish.
- The kanban grid spans roughly two viewport heights so the entire board scrolls end-to-end, with the backlog note and column headers anchored while columns grow vertically together; this enables both desktop and mobile heights to reveal content without internal horizontal scrolling.
- All pipeline columns now get their own scrollable list when they overflow, so “Applied” and the other stages show a local scrollbar only when they contain more cards than the viewport, keeping each column independent while the board still scrolls as a single page.
- The side rail defaults to a collapsed icon strip that expands on hover or via the burger toggle, and each icon surfaces its label on hover when the rail is collapsed.

## Manual job workflow

- Manual job creation submits immediately, opens the detail drawer, and enqueues enrichment/formatting in the background (`BackgroundTasks`); the kanban board auto-refreshes silently once the backend work completes, avoiding a multi-second blocking spinner.

## Component map

- `App.tsx`
  - route registration and global theme state/persistence
- `components/layout/AppShell.tsx`
  - shared side rail + route navigation + theme switch
- `pages/BoardPage.tsx`
  - board data loads, kanban interactions, detail drawer orchestration
  - route-remount cache hydration (jobs/stats/profile/filter state/detail+event caches)
- `pages/ProfilePage.tsx`
  - profile load/edit/save workflow and dirty-state handling
- `pages/AnalyticsPage.tsx`
  - funnel analytics fetch + preset controls + conversion visualization
  - goals/alerts controls and cards
- `components/KanbanColumn.tsx`
  - drop zone and column frame
- `components/JobCard.tsx`
  - draggable summary card + match badge
- `components/DetailDrawer.tsx`
  - selected job detail view
  - inline tracking editor
  - skill alignment matrix (`matched` vs `gaps`) with one-click add-to-profile for missing skills
  - fuzzy/canonical skill comparison (acronym, compact, and punctuation-variant tolerant)
  - enrichment + timeline sections
  - destructive `Delete Job` action (confirmed) in drawer footer
  - description rendering prefers `enrichment.formatted_description` (Markdown) and falls back to raw `job.description`
- `components/ThemeToggle.tsx`
  - custom star/cloud switch
- `components/reactbits/SpotlightSurface.tsx`
  - pointer-reactive radial spotlight wrapper
- `components/reactbits/ShimmerTag.tsx`
  - animated metadata/skill chip

## Responsive behavior

- Desktop: shell header + route tabs; full-width board with right slide-in detail drawer.
- Tablet/mobile: horizontally scrollable columns, drawer constrained to viewport width.
- Stats cards collapse from 4 columns to 2 and then 1 on narrow screens.
- Profile editor collapses from 2-column cards to stacked single-column layout.

Commands:

```bash
npm install
npm run dev
npm run build
npm run preview
```

Scoring details: [`match-scoring.md`](match-scoring.md).
