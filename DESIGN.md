---
version: alpha
name: Roster-design-system
source: https://github.com/VoltAgent/awesome-design-md (design-md/supabase, MIT)
description: >
  Roster's design language, adapted from the Supabase-inspired analysis in
  awesome-design-md. A clean white-and-near-black system with a single
  signature emerald CTA, a geometric humanist sans, and dense product UI as
  the centre of gravity. Quietly technical: minimal chrome, near-monochrome
  palette, and the green primary acting as the only chromatic event on the
  page.

colors:
  primary: "#3ecf8e"
  primary-hover: "#4ade9e"
  primary-deep: "#24b47e"
  on-primary: "#0a0a0a"
  ink: "#ededed"
  ink-secondary: "#d4d4d4"
  ink-mute: "#a1a1a1"
  ink-mute-2: "#8f8f8f"
  ink-faint: "#5c5c5c"
  canvas: "#0a0a0a"
  canvas-soft: "#1a1a1a"
  canvas-raised: "#262626"
  hairline: "#2e2e2e"
  hairline-strong: "#454545"
  hairline-cool: "#242424"
  # Status colours — Roster addition. A scheduling tool has to say
  # "unattended shop" and "please confirm" in a way no marketing site does.
  danger: "#b42318"
  danger-soft: "#fef3f2"
  danger-hairline: "#fecdca"
  warn: "#b54708"
  warn-soft: "#fffaeb"
  warn-hairline: "#fedf89"

typography:
  display-xxl: { fontFamily: Inter, fontSize: 64px, fontWeight: 500, lineHeight: 1.1, letterSpacing: -1.92px }
  display-xl:  { fontFamily: Inter, fontSize: 48px, fontWeight: 500, lineHeight: 1.1, letterSpacing: -1.44px }
  display-lg:  { fontFamily: Inter, fontSize: 36px, fontWeight: 500, lineHeight: 1.15, letterSpacing: -0.72px }
  display-md:  { fontFamily: Inter, fontSize: 28px, fontWeight: 500, lineHeight: 1.2, letterSpacing: -0.42px }
  heading-lg:  { fontFamily: Inter, fontSize: 22px, fontWeight: 500, lineHeight: 1.2, letterSpacing: 0 }
  heading-md:  { fontFamily: Inter, fontSize: 18px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0 }
  body-lg:     { fontFamily: Inter, fontSize: 18px, fontWeight: 400, lineHeight: 1.55, letterSpacing: 0 }
  body-md:     { fontFamily: Inter, fontSize: 16px, fontWeight: 400, lineHeight: 1.5, letterSpacing: 0 }
  button-md:   { fontFamily: Inter, fontSize: 14px, fontWeight: 500, lineHeight: 1.0, letterSpacing: 0 }
  caption:     { fontFamily: Inter, fontSize: 13px, fontWeight: 400, lineHeight: 1.45, letterSpacing: 0 }
  micro:       { fontFamily: Inter, fontSize: 12px, fontWeight: 400, lineHeight: 1.45, letterSpacing: 0 }
  code:        { fontFamily: "ui-monospace, Menlo, Monaco, Consolas, monospace", fontSize: 14px, fontWeight: 400, lineHeight: 1.5 }

rounded: { xs: 4px, sm: 6px, md: 8px, lg: 12px, xl: 16px, full: 9999px }

spacing: { xxs: 2px, xs: 4px, sm: 8px, md: 12px, lg: 16px, xl: 24px, xxl: 32px, huge: 64px }
---

## Overview

Roster is **Carbon**: the Supabase *dashboard* register rather than their
white marketing site. Surfaces sit on `{colors.canvas}` (`#0a0a0a`, neutral
charcoal — never pure black for the page), with text in `{colors.ink}`
(`#ededed`). The only consistent chromatic event is the **emerald primary**
(`#3ecf8e`), used as the filled CTA and nothing else. Everything else is a
calibrated grey ladder.

There is no atmospheric gradient, no glassmorphism, no glow. The roster grid
is the argument — it sits inside a 12px container with a 1px hairline and is
allowed to be the densest thing on screen.

**Key characteristics**

- Single emerald primary as the only chromatic event; everything else monochrome.
- Charcoal canvas with a greyscale hierarchy from `{colors.hairline-cool}` to `{colors.ink}`.
- Inter at weight 500 for display with negative letter-spacing; 400 for body.
- Tight 6px button radii — square-ish, technical, never pill-shaped.
- Near-black type on the emerald button, not white. The green reads as a lit
  surface, not a coloured chip.

## Surfaces on a dark canvas

Elevation is a **lighter surface**, not a shadow — a drop shadow against
near-black is invisible. The steps are wider than they look like they need to
be, because contrast compresses badly at the dark end: `#0a0a0a` to `#141414`
measures 1.07:1, which is not enough for a card to read as a distinct surface
at all. The shipped steps are:

| Token | Value | Separation | Use |
|---|---|---|---|
| `{colors.canvas}` | `#0a0a0a` | — | page |
| `{colors.canvas-soft}` | `#1a1a1a` | 1.14:1 above page | in-flow card, grid cell |
| `{colors.canvas-raised}` | `#262626` | 1.15:1 above card | modal, popover |

Hover on the emerald button goes **brighter** (`{colors.primary-hover}`), not
deeper. On a dark canvas a darker hover state reads as disabled.

## Print is always white

The rota gets printed and pinned to a wall, so the print stylesheet forces a
white page regardless of what the screen is doing. That block is the one
place `!important` colour overrides are legitimate; nothing in it leaks into
the app.

## Roster-specific rules

These extend the source analysis; a marketing site has no equivalent.

### One emerald per viewport

The filled green button is the single most important action on the screen —
**Generate** on the roster page, **Save** in a form, **Approve** once a
roster exists. Everything else is `button-secondary-outline`. If two green
buttons are visible at once, one of them is wrong.

### Role badges follow the hierarchy, not the rainbow

Role colour encodes *seniority*, not identity, so it must read as one ramp
rather than five unrelated hues. On a dark canvas the ramp runs **brightest =
most senior**: managers are a near-white chip, supervisors mid-grey, floor
staff a bare outline. Night shifts get the one recessed surface (pure black)
— they are the hardest slot to fill and the easiest to overlook, and that
reads as "after hours" without introducing a hue. Never let a role badge use
emerald; that is reserved for actions.

### Status is the one place colour is allowed to shout

An unattended hour is a broken guarantee and gets `{colors.danger}` on
`{colors.danger-soft}`. An unfamiliar shift needing confirmation gets
`{colors.warn}`. Advisories stay monochrome. Three tiers, visually distinct
at a glance, in that order of severity.

### The grid is data, not decoration

No shadows, no hover lift, no transitions on grid cells beyond a background
change. A filled cell is a hairline box with mono times. An empty cell is a
dashed hairline. Anything more animates 200 cells at once.

## Components

**`button-primary`** — background `{colors.primary}`, text
`{colors.on-primary}` (near-black, *not* white), 14px/500, padding 8px 16px,
radius `{rounded.sm}` 6px. Pressed shifts to `{colors.primary-deep}`.

**`button-secondary`** — background `{colors.canvas}`, text `{colors.ink}`,
1px `{colors.hairline-strong}` border, same shape.

**`button-danger`** — text `{colors.danger}` on transparent, 1px
`{colors.danger-hairline}`. Used for destructive actions only.

**`card`** — background `{colors.canvas}`, 1px `{colors.hairline}`, radius
`{rounded.lg}` 12px, padding 24–32px. Flat by default.

**`text-input`** — background `{colors.canvas}`, 1px `{colors.hairline}`,
radius `{rounded.sm}`, padding 8px 12px. Focus ring is emerald at 15%.

**`pill`** — `{typography.micro}`, padding 2px 8px, radius `{rounded.full}`.

## Elevation

| Level | Treatment | Use |
|---|---|---|
| 0 | Flat, 1px hairline | Default cards, grid cells |
| 1 | `0 1px 3px rgba(0,0,0,0.06)` | Subtle lift on hover for clickable cards |
| 2 | `0 8px 24px rgba(0,0,0,0.08)` | Dropdowns, popovers |
| 3 | `0 16px 48px rgba(0,0,0,0.12)` | Modal overlays |

## Do's and Don'ts

### Do
- Reserve emerald for filled CTAs — one per viewport.
- Render display tiers at weight 500 with negative letter-spacing.
- Use 6px radii for buttons and inputs.
- Use near-black on the emerald button.
- Keep the roster grid flat and dense.

### Don't
- Don't introduce accent colours as system colours. Status red and amber are
  the only exceptions, and only for coverage problems.
- Don't bump display weight above 500 — the calibrated mid-weight breaks at 600+.
- Don't use pill-shaped buttons.
- Don't use white text on the emerald button.
- Don't add gradients, glass blur, or glow. Flat surfaces and hairlines only.
- Don't use pure black for the page — `#0a0a0a` leaves room for a recessed
  surface below it, which the night-shift badge uses.
- Don't reach for a drop shadow to separate surfaces; step the lightness.

## Responsive

| Name | Width | Key changes |
|---|---|---|
| Wide | ≥ 1440px | Full container; grid at full scale |
| Desktop | 1024–1440px | Sidebar sticky; grid scrolls horizontally |
| Tablet | 768–1023px | Sidebar collapses to a drawer |
| Mobile | < 768px | Display drops 64 → 36px; grid scrolls |

Touch targets ≥ 36×36px. Form fields ≥ 36px tall.

## Agent prompt guide

> Build this using DESIGN.md. Charcoal canvas `#0a0a0a`, cards `#1a1a1a`,
> modals `#262626`, ink `#ededed`, emerald `#3ecf8e` for the single primary
> action only. Inter, weight 500 for headings with tight negative tracking,
> 400 for body. 6px radii on buttons and inputs, 12px on cards. Flat — 1px
> hairlines, elevation by lighter surface rather than shadow, no gradients,
> no blur, no glow.

---

Adapted from [awesome-design-md](https://github.com/VoltAgent/awesome-design-md)
(MIT). The source analysis describes publicly visible CSS values of a
third-party site; Roster uses it as a starting point, not a claim of
affiliation.
