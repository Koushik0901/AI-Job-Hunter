---
name: Eucalyptus & Earth Intelligence
project: Kenji — AI Job Hunter
version: 1.0
colors:
  # Surfaces
  surface: '#f7faf7'
  surface-dim: '#d7dbd8'
  surface-bright: '#ffffff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f1f4f2'
  surface-container: '#ebefec'
  surface-container-high: '#e6e9e6'
  surface-container-highest: '#e0e3e1'
  on-surface: '#181c1b'
  on-surface-variant: '#3f4947'
  outline: '#6f7977'
  outline-variant: '#bec9c6'

  # Primary — Sage
  primary: '#006055'
  on-primary: '#ffffff'
  primary-container: '#24796d'
  on-primary-container: '#affff0'
  primary-tint: 'rgba(0,96,85,0.08)'
  primary-tint-2: 'rgba(0,96,85,0.14)'

  # Secondary — Muted Forest
  secondary: '#47645e'
  on-secondary: '#ffffff'
  secondary-container: '#c7e6df'
  on-secondary-container: '#4c6862'

  # Tertiary — Terracotta
  tertiary: '#82442f'
  on-tertiary: '#ffffff'
  tertiary-container: '#ffdbd0'
  on-tertiary-container: '#713623'
  tertiary-tint: 'rgba(130,68,47,0.08)'

  # Signals
  error: '#ba1a1a'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  warn: '#9a6a1f'
  warn-container: '#ffe3bf'

typography:
  display:
    fontFamily: "'Manrope', ui-sans-serif, system-ui, sans-serif"
    usedFor: "headlines, metric numbers, brand mark, product names inline"
  body:
    fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif"
    usedFor: "UI text, body copy, labels, buttons"
  mono:
    fontFamily: "'JetBrains Mono', ui-monospace, Menlo, monospace"
    usedFor: "tool-call payloads, IDs, timestamps, metadata, tags, overlines"

radii:
  sm: 4px
  default: 8px
  md: 12px
  lg: 16px    # cards, main containers
  xl: 24px
  pill: 9999px # chips, tags, AI input

spacing:
  unit: 4px
  page-padding: 48px
  page-padding-compact: 28px
  stack-xs: 8px
  stack-sm: 12px
  stack-md: 20px
  stack-lg: 32px
  section-gap: 36–48px
  card-padding: 20–24px
  sidebar-width: 260px

shadows:
  shadow-1: '0 1px 2px rgba(24,28,27,0.04), 0 1px 1px rgba(24,28,27,0.03)'
  shadow-2: '0 2px 6px rgba(24,28,27,0.04), 0 8px 24px -8px rgba(24,28,27,0.08)'
  shadow-3: '0 12px 32px -8px rgba(24,28,27,0.10), 0 4px 10px -2px rgba(24,28,27,0.05)'
  shadow-lift: '0 24px 56px -16px rgba(24,28,27,0.18), 0 4px 12px -2px rgba(24,28,27,0.06)'
---

# Kenji — Design System

*Eucalyptus & Earth Intelligence — v1.0*

## 1. Brand & Principles

Kenji is a private, local-first AI job agent. The interface should feel like a **serene, high-end workspace** — composed, confident, and technologically mature. The opposite of a job-board: not a firehose of postings with dopamine hooks, but a calm console where an agent does real work on your behalf, and you stay in control.

Four principles underpin every decision:

1. **Organic intelligence** — the app is smart, but it should feel grown, not generated. Warm off-whites, sage greens, and earthy terracotta accents replace the cold blue/purple of typical AI UIs.
2. **Less but better** — extreme clarity and breathing room. Reduce cognitive load at every step.
3. **Groundedness over polish** — every surface (tool call, bullet edit, cover-letter phrase) should trace back to something the user actually wrote.
4. **Approval-first** — the agent announces, the user approves. Never hidden autonomy.

---

## 2. Color

### 2.1 The three voices

The palette encodes three distinct voices. Use them with intent — do not mix.

| Voice | Token | Color | Where it belongs |
|---|---|---|---|
| **Primary (Sage)** | `--primary` `#006055` | Deep, steady green | Agent voice, CTAs, match-success states, "on" state |
| **Secondary (Muted Forest)** | `--secondary` `#47645e` | Grounded gray-green | Active nav, structural emphasis, user-side elements |
| **Tertiary (Terracotta)** | `--tertiary` `#82442f` | Warm earthy red | Approval moments, human-in-the-loop cues, careful highlights |

### 2.2 Surfaces

Light, warm off-white canvas. Elevation comes from tonal layers plus diffuse shadow — never heavy borders.

- `--surface` `#f7faf7` — page background
- `--sc-lowest` `#ffffff` — cards, elevated surfaces
- `--sc-low → sc-highest` — subtle sectioning (tinted grays)
- `--outline-variant` `#bec9c6` — hairline dividers

### 2.3 Signals

- **Error** `#ba1a1a` — only for destructive states / removed-text diffs
- **Warn** `#9a6a1f` — approval-pending states, soft cautions
- **Success** — reuses `--primary` (sage) rather than a separate green

### 2.4 Rules

- Never saturate the canvas above `chroma 0.02` for off-whites.
- Use primary sparingly — one primary CTA per view, max.
- Tertiary is a **seasoning**, not a color. If two tertiary elements share a screen, question one of them.
- Accents always share chroma & lightness across semantic pairs (e.g. `primary-tint` and `tertiary-tint` both at 8% opacity).

---

## 3. Typography

Three families, each with a clearly scoped job.

| Family | Weights | Role |
|---|---|---|
| **Manrope** | 500, 600, 700, 800 | Display: headlines, metric numbers, section kickers, brand name inline |
| **Inter** | 300, 400, 500, 600, 700 | All UI: body, buttons, labels, nav |
| **JetBrains Mono** | 400, 500 | Machine voice: tool-call payloads, IDs, timestamps, `.mono` tags |

### 3.1 Scale (body-first)

| Role | Family | Size / Line | Weight | Letter-spacing |
|---|---|---|---|---|
| `headline` | Manrope | 56 / 1.02 | 700 | -0.03em |
| `h1` (topbar) | Manrope | 22 / 1.15 | 600 | -0.018em |
| `h2` | Manrope | 32 / 1.25 | 600 | -0.01em |
| `h3` | Manrope | 24 / 1.33 | 600 | 0 |
| `metric-num` | Manrope | 40 / 1.0 | 700 | -0.025em |
| `body-lg` | Inter | 18 / 1.55 | 400 | 0 |
| `body` | Inter | 14 / 1.5 | 400 | 0 |
| `agent-text` | Inter | 15 / 1.6 | 400 | 0 |
| `label-caps` / `overline` | Inter | 11 / 1.35 | 600–700 | 0.08–0.14em, uppercase |
| `button` | Inter | 13.5 / 1 | 500 | 0.01em |
| `mono` | JetBrains Mono | 10.5–12 | 400–500 | 0 |

### 3.2 Rules

- Headlines are **tight** (`-0.02` to `-0.03em`). Body is neutral. Overlines breathe (`+0.08em`).
- Maintain generous `line-height: 1.55–1.6` on body for a luxurious, readable feel.
- Overlines always preceded by a 24×2px primary bar (`.overline::before`). They are **always** uppercase.
- Never nest more than two type families in a single paragraph.

---

## 4. Shape & Radii

| Token | px | Use |
|---|---|---|
| `--r-sm` | 4 | Diff line highlights, kbd keys |
| `--r` | 8 | Buttons, inputs, small components |
| `--r-md` | 12 | Tool-call cards, tweak panels, composers |
| `--r-lg` | 16 | Primary cards, modal frames |
| `--r-xl` | 24 | Hero containers |
| `--r-pill` | 9999 | Chips, tags, AI input, status indicators |

**Shape language: soft professional.** 8px is the default. Pills exclusively convey *approachability* — chips, tags, progress bars, the AI input.

---

## 5. Elevation

Four tiers. Prefer tonal contrast first; use shadow only where interactivity or floating context requires it.

| Token | Depth | Use |
|---|---|---|
| `--shadow-1` | subtle | Flat resting buttons, inline cards |
| `--shadow-2` | standard | Cards, job entries, tool calls |
| `--shadow-3` | raised | Interview panel, focused cards |
| `--shadow-lift` | floating | Tweaks panel, modals, popovers |

Shadows use `rgba(24,28,27, α)` — never pure black. Soft, warm, desaturated.

---

## 6. Layout & Spacing

### 6.1 Grid

- **Desktop:** fixed grid, 260px sidebar + fluid main. Content max-width 1280px centered.
- **Side padding:** 48px default, 28px in compact density mode.
- **Gutters:** 24px between columns, 10–14px between cards in a list.

### 6.2 Rhythm

- Base unit: **4px**. All spacing snaps to this.
- Common spacings: `8, 12, 16, 20, 24, 32, 40, 48, 64`.
- Between major sections: **36–48px**, paired with a hairline divider.

### 6.3 Density tweak

The app ships a density tweak. Compact mode halves vertical padding on nav items, trims content padding to 28px, and tightens agent-message gutters. Both densities must read well — test every new component at both.

---

## 7. Components

### 7.1 Buttons

- **Primary** — sage background, white text, `box-shadow: 0 4px 12px -4px rgba(0,96,85,0.4)`. One per view.
- **Secondary** — muted-forest background, white text.
- **Default** — white card background, 1px `--outline-variant`, `shadow-1`.
- **Ghost** — transparent, surfaces on hover. For low-priority actions.
- **Tertiary-ghost** — terracotta-tinted. Only for human-review / approval secondary actions.
- Sizes: `sm` (6×10, 12.5px), default (9×14, 13.5px), `lg` (12×20, 14.5px).
- Icons precede labels at 11–13px, 1.5px stroke.

### 7.2 Chips

Pill-shaped. Always carry meaning — never decorative.

- **Default** — light gray bg, muted text.
- **Primary** — 8% sage bg, sage text. "Top match", "grounded".
- **Primary-strong** — primary-container bg, white text. Used rarely for emphasis.
- **Tertiary** — terracotta container. Human-review flags.
- **Ghost** — transparent, outline border. Source tags, team size.
- **Mono** — monospace, `0` letter-spacing, smaller. IDs, technical tags.

### 7.3 Cards

16px radius, white background, `shadow-2`. Variants:

- `.card.subtle` — no shadow, `sc-low` background.
- `.card.bordered` — no shadow, outline-variant border.
- `.card.lifted` — upgraded to `shadow-3`.

Cards never use a left-border accent stripe as decoration. If a card needs semantic coloring, use a chip, an overline, or a small `ni-dot`.

### 7.4 Inputs

- 1px `--outline-variant` border, 8px radius, 12×14 padding.
- Focus: border → `--outline`, no blue glow. Subtle.
- Textareas breathe at `line-height: 1.55`.

### 7.5 Agent message

- 32×32 square-rounded avatar (10px radius).
- Agent avatar: sage bg, white "K", small cast shadow.
- User avatar: terracotta linear gradient, initials.
- Name line → mono timestamp 10.5px separated by 10px.
- Body max-width 68ch for readability. Italic emphasis uses Manrope italic in sage.

### 7.6 Tool call

A card that documents a single machine action.

- Header: mono glyph (▸) + mono name + status chip (`spinner` / `✓ done` / `awaiting approval`).
- Body: key-value lines, monospace, 11.5px. Keys in `--outline`, values in `--on-surface`.
- `line.good` highlights positive-outcome values in sage.
- Approval bar: dashed top border, terracotta-tint background, reject + approve buttons.

### 7.7 Score ring

Circular SVG arc. Stroke width scales with size (3 at 48px, 3.5 at 56px). Color by threshold:

- ≥ 85: `--primary` (sage)
- 70–84: `--tertiary` (terracotta)
- < 70: `--warn`

Value centered in Manrope 700.

### 7.8 Radar

Four-axis polygon on three concentric rings. Fill `rgba(0,96,85,0.16)`, stroke primary 1.5px, 3px primary vertex dots. Axis labels Inter 10 / 600 in `--on-surface-variant`.

### 7.9 AI progress bar

4px tall pill, `--sc-high` track. Fill is a linear gradient from sage → terracotta with a shimmer overlay. Only use for agent progress — not generic loading.

---

## 8. Motion

Kenji animates to communicate, not to delight.

- **Fade-in** on screen change (`320ms ease`, 6px upward drift).
- **Stagger** children in lists on first render (70ms increments).
- **Typing dots** while agent is thinking (1.2s pulse).
- **Pulse dot** for active / live states (2s infinite). Two distinct uses:
  - **In-context** (topbar chip, agent avatar): the agent is currently working in the view you're looking at.
  - **Cross-screen unread** (Command nav item): the agent finished a reply while you were elsewhere. Clears the moment you enter Command.
- **Shimmer** on active progress bars (2.2s infinite).

Never:

- Bounce, spring, or overshoot.
- Animate color shifts on hover for primary text.
- Fade in something that shouldn't have been hidden in the first place.

---

## 9. Iconography

- 1.5px stroke, rounded caps, 24×24 viewBox.
- Kenji's icon set is deliberately **small** (~30 glyphs) to avoid the corporate-icon-library feel.
- Icons live inline with text at 11–14px. Match the text color; never tint unless the whole element carries semantic color.
- No emoji anywhere. No filled icons. No decorative dingbats.

---

## 10. Voice & Copy

- **Machine copy** (tool names, IDs, keys) is `snake_case` and monospace. `scrape.job_posting`, `match.stories_to_jd`.
- **Product copy** is plain, lowercase-led, no exclamation marks. "124 roles, ranked to you."
- **Agent copy** is warm, second-person, occasionally italicizing a keyword in sage for emphasis. Never apologizes; announces.
- **Overlines** are terse technical phrases: "run timeline", "grounding · every edit → a story", "recruiter red-team".
- Numbers in agent text are inline mono for scannability.

---

## 11. Application rules

### What Kenji looks like when it's working

- The agent avatar is always in sage.
- An active run shows a pulsing sage dot in the nav and topbar chip.
- A tool call in flight shows `spinner` status. A completed one shows sage `✓ done`.
- An approval-pending tool shows a **terracotta-tinted bar** at the bottom — this is the only moment the user sees terracotta prominently.

### What Kenji looks like when it's waiting for you

- Typing dots, paused at the bottom of the thread.
- Composer chip shows the current target.
- Pipeline counts in the sidebar are in mono.

### What Kenji looks like when it finished while you were away

The agent runs across navigations — sending a message and switching screens is a normal flow, not an interruption. The interface signals completion without yanking attention:

- A **sage pulse dot** appears next to the **Command** nav item the moment an assistant reply lands while the user is on any other screen.
- The dot is the *only* surface for this signal. No toast, no badge count, no sound, no titlebar flash. The principle is "communicate, don't decorate" — one quiet dot is enough.
- Entering the Command screen clears it immediately. The dot is unread-state, not a notification log.
- Implementation note: agent chat state lives in `DataContext`, not in `Command.tsx`, because the screen unmounts on navigation. The context owns `agentUnread` and an `onAgentScreen` ref so off-screen replies can flip the flag without losing message history. Any future agent-driven surface must route writes through `sendAgentMessage` so this signal stays accurate.

### What Kenji must never do

- Autonomously submit an application.
- Invent a claim not traceable to a story.
- Render a dark-mode toggle (Kenji is light-first by principle — the calm workspace).
- Use red/green as the only signal for a state (color-blind accessibility).
- Stack more than one primary CTA in a single view.

---

## 12. Tokens reference (CSS)

All tokens live in `:root` inside `styles.css`. The file also ships a **compat layer** that maps legacy tokens (`--ink`, `--bg`, `--accent`, `--line`, etc.) to the new system, so components built against the old dark theme keep rendering during migration. New work should use the canonical tokens only.

```
--surface, --sc-lowest, --sc-low, --sc, --sc-high, --sc-highest
--on-surface, --on-surface-variant, --outline, --outline-variant
--primary, --on-primary, --primary-container, --primary-tint, --primary-tint-2
--secondary, --secondary-container, --on-secondary-container
--tertiary, --tertiary-container, --tertiary-tint
--error, --warn, --error-container, --warn-container
--r-sm, --r, --r-md, --r-lg, --r-xl, --r-pill
--shadow-1, --shadow-2, --shadow-3, --shadow-lift
--font-display, --font-sans, --font-mono
```

---

## 13. Open questions / future

- **Dark mode.** Intentionally deferred. If added, it must *not* simply invert surfaces — the whole sage/terracotta relationship needs rethinking against a warm near-black.
- **Data visualization.** Only the radar & score ring exist today. A future charting language needs its own spec (this document will grow a §14).
- **Mobile.** The current layout is desktop-first. Mobile collapse rules are pending real use-cases.
- **Empty states.** Not yet patterned. When they appear, follow the "less but better" rule: a single sentence in `--on-surface-variant`, one CTA, no illustrations.
