# MuniSense design system

**This is the design system the P6 staff console must implement.** Until then it governs the README and its assets (`docs/assets/`). The owner set the direction: Apple-inspired restraint, editorial typography, glass used selectively (P1-17, E45). No CSS or UI code exists yet; these are the tokens and rules the console will turn into code.

## Principles

1. **Restraint.** Cream, black and one green. Space and type do the work, not colour.
2. **Colour carries meaning.** Pine Green means verified or important, and nothing else. Every status uses the same colour everywhere.
   - **Allowed:** verified status, focus rings, links, and a single brand accent (the rule under the wordmark).
   - **Not used for:** citations, "built" markers or decoration, so an estimated value never looks verified at a glance.
3. **Numbers are facts.** Money and kWh are set in tabular monospace, right-aligned, never abbreviated.
4. **Colour is never the only signal.** A status is always a dot *and* a word.

## Colour tokens

Every text colour below meets WCAG AA (at least 4.5:1) on every surface it is used on. The ratios were computed with the WCAG 2 relative-luminance formula. For each mode they are given against the main page surface first and the other surface second (light: `surface`, then `surface-sunken`; dark: `surface`, then `surface-tinted`). Against pure white the light ratios are slightly higher still.

### Light

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `surface` | `#FDFDFD` (Skeleton Cream) | page | — |
| `surface-raised` | `#FFFFFF` | cards, table rows | — |
| `surface-sunken` | `#F4F4F2` | table headers, planned diagram nodes | — |
| `text` | `#060606` (Deep Black) | primary text | 19.9:1 on `surface`; 18.4:1 on `surface-sunken` |
| `text-secondary` | `#52524E` | labels, captions | 7.7:1; 7.1:1 |
| `accent` | `#016030` (Pine Green) | verified, important, focus, links | 7.6:1; 7.0:1 |
| `status-verified` | `#016030` | verified dot and label | as `accent` |
| `status-estimated` | `#62625E` | estimated dot and label | 6.0:1; 5.6:1 |
| `status-user-provided` | `#8A4B1C` | user-provided dot and label | 6.7:1; 6.1:1 |
| `hairline` | `#060606` at 10% | borders, rules | — |
| `on-accent` | `#FDFDFD` | text on a Pine fill | 7.6:1 on `#016030` |

### Dark

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `surface` | `#060606` (Deep Black) | page | — |
| `surface-raised` | `#121413` | cards, table rows | — |
| `surface-tinted` | `#0B1A12` | hero field (deep pine) | — |
| `text` | `#FDFDFD` (Skeleton Cream) | primary text | 19.9:1 on `surface`; 17.6:1 on `surface-tinted` |
| `text-secondary` | `#A8A8A3` | labels, captions | 8.5:1; 7.5:1 |
| `accent` | `#3DBE7E` (Pine tint) | verified, important, focus, links | 8.6:1; 7.6:1 |
| `status-verified` | `#3DBE7E` | verified dot and label | as `accent` |
| `status-estimated` | `#A1A19C` | estimated dot and label | 7.8:1; 6.9:1 |
| `status-user-provided` | `#E0A06A` | user-provided dot and label | 9.1:1; 8.0:1 |
| `hairline` | `#FDFDFD` at 14% | borders, rules | — |

Pine Green (`#016030`) itself is too dark to use as text on dark surfaces (2.5:1 on `#0D1117`), and the Pine tint is too light on light surfaces (2.4:1 on white). Each mode uses only its own accent.

### Component tokens

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `citation-chip` | `text-secondary` on `hairline` at 4%, border `hairline` at 22% | the same with the dark tokens | a page citation ("Schedule p. 4"); neutral, never Pine |
| `diagram-built` | fill `#060606`, border `#A8A8A3`, text `#FDFDFD` (19.9:1) | the same | built modules in diagrams |
| `diagram-planned` | fill `#F4F4F2`, dashed border `#767671`, text `#52524E` (7.1:1) | the same | planned modules, labelled with their phase |
| `badge-neutral` | `#52524E` with white text (7.9:1) | the same | README badges other than CI |

Diagram nodes use solid fills with their own text colour, so they read on GitHub's light and dark pages alike. Each node needs its fill or its border at least 3:1 against the page, so its edge is visible. Built nodes: the fill is 20.3:1 on white and the border 7.9:1 on GitHub dark (`#0D1117`). Planned nodes: the border is 4.6:1 on white and 4.2:1 on GitHub dark.

### Status, used identically everywhere

| Status | Dot and label (light / dark) | Meaning |
| --- | --- | --- |
| Verified | `#016030` / `#3DBE7E` | checked by a human against the source (ADR-0006) |
| Estimated | `#62625E` / `#A1A19C` | not verified; the reason is always available |
| User-provided | `#8A4B1C` / `#E0A06A` | from a user's own bill or receipt |

## Typography

| Role | Face | Size / line height | Notes |
| --- | --- | --- | --- |
| Wordmark and the single largest headline | Bodoni Moda (SIL Open Font License 1.1), optical size 96, weight 500 | display: cap height 82 px in the banner | Always converted to outlined paths, so it renders the same everywhere; never live text, never body copy (`docs/assets/FONTS.md`) |
| Headline | system sans | 30 / 38 | `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif` |
| Title | system sans | 22 / 30 | |
| Body | system sans | 16 / 24 | |
| Caption | system sans | 14 / 20 | secondary text |
| Small | system sans | 12 / 16 | never below 12 |
| Numbers | system monospace, `font-variant-numeric: tabular-nums` | as the surrounding role | `ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace`; money and kWh right-aligned |

## Spacing, radii, shadows

- **Spacing.** A 4 px base, using only 4, 8, 12, 16, 24, 32, 48 and 64.
- **Radii.** 6 px for controls, 12 px for cards and tables, 24 px for the glass card, and fully round for chips and status dots.
- **Shadows.** There are two. The light shadow is `0 18px 44px rgba(6,6,6,0.10)`; the dark one is `0 18px 44px rgba(0,0,0,0.45)`. Shadows go only on the glass card and on overlays (menus, dialogs). Tables and diagrams have none.

## Glass

**The recipe:**
- **Fill:** `#FFFFFF` at 62% in light, `#FDFDFD` at 6% in dark.
- **Backdrop blur:** `backdrop-filter: blur(24px) saturate(140%)`, in the console only (SVG cannot blur what is behind it).
- **Border:** a 1 px hairline.
- **Radius:** 24 px.
- **Shadow:** the light or dark shadow above.
- **Field:** a subtle field behind it, cream to white in light, black to deep pine (`#060606` to `#0B1A12`) in dark.

**Where glass is allowed:** only the one featured bill card. That means the hero banner now, and in P6 at most one featured summary card per screen.

**Where glass is never used:** tables, diagrams, forms, navigation, long text, and anything holding more than one bill line. These are solid surfaces.

## Focus and motion

- **Focus.** A 2 px `accent` outline with a 2 px offset, on every interactive element. It is never removed or hidden, and it works the same with keyboard and pointer.
- **Motion.** Only state changes, 150 to 200 ms, ease-out. No parallax, auto-play or looping animation.
- **Reduced motion.** Under `prefers-reduced-motion: reduce`, transitions become instant, except opacity fades of at most 100 ms.
- **Dark mode.** It follows `prefers-color-scheme`, and the console also offers an explicit choice.

## Assets

| Asset | What |
| --- | --- |
| `docs/assets/hero-light.svg`, `hero-dark.svg` | README banner, shown through `<picture>` and `prefers-color-scheme` |
| `docs/assets/social-preview.png` | 1280×640 GitHub social preview, rendered from the light banner (the owner uploads it) |
| Diagrams in `README.md` | Mermaid. Built modules are solid dark (`diagram-built`); planned ones are a solid light fill with a dashed border and their phase (`diagram-planned`) |

Each asset is updated at every phase gate, when the README status table and highlights are (`docs/README.md`).
