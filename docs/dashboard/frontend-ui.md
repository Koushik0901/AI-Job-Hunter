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
- Shared shell: top header, route nav tabs, theme toggle.

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
- Smooth 200ms theme transition (disabled with `prefers-reduced-motion`).
- Board route keeps in-memory state cache for fast return navigation (`Board -> Profile -> Board`) without immediate refetch.
- Detail drawer uses background prefetch and cache reuse for job detail + timeline where available.

## Component map

- `App.tsx`
  - route registration and global theme state/persistence
- `components/layout/AppShell.tsx`
  - shared app header + route navigation + theme switch
- `pages/BoardPage.tsx`
  - board data loads, kanban interactions, detail drawer orchestration
  - route-remount cache hydration (jobs/stats/profile/filter state/detail+event caches)
- `pages/ProfilePage.tsx`
  - profile load/edit/save workflow and dirty-state handling
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
  - description rendering prefers `enrichment.formatted_description` and falls back to raw `job.description`
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
