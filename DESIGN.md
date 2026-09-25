---
# gstack: design-md-format=spec
name: TradingBot
description: Industrial precision meets luxury restraint — a Swiss watch control room for automated equity trading
colors:
  primary: "#d4a015"
  on-primary: "#070a0f"
  surface: "#0f1419"
  surface-elevated: "#161d26"
  text: "#c9d1d9"
  text-heading: "#e6edf3"
  text-muted: "#5a6a7f"
  accent: "#d4a015"
  accent-hover: "#e5b320"
  success: "#2da44e"
  warning: "#d4a015"
  error: "#f85149"
  background: "#070a0f"
  border: "#1c2736"
typography:
  display:
    fontFamily: Satoshi
    fontWeight: 700
    fontSize: clamp(1.25rem, 2vw, 1.5rem)
    letterSpacing: -0.01em
  body:
    fontFamily: Instrument Sans
    fontSize: 0.8125rem
    lineHeight: 1.5
  label:
    fontFamily: Instrument Sans
    fontSize: 0.6875rem
    letterSpacing: 0.06em
  mono:
    fontFamily: JetBrains Mono
    fontFeature: tnum
rounded:
  sm: 4px
  md: 6px
  lg: 8px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "#ffffff"
  button-outline:
    borderColor: "{colors.border}"
    textColor: "{colors.text}"
  button-save:
    backgroundColor: "rgba(212,160,21,0.2)"
    textColor: "{colors.accent}"
    borderColor: "rgba(212,160,21,0.3)"
  input:
    borderColor: "rgba(28,39,54,0.5)"
    backgroundColor: "rgba(22,29,38,0.3)"
    rounded: "{rounded.md}"
  input-focus:
    borderColor: "rgba(212,160,21,0.5)"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "rgba(28,39,54,0.5)"
    rounded: "{rounded.lg}"
  nav-link:
    textColor: "{colors.text-muted}"
  nav-link-active:
    textColor: "{colors.accent}"
    backgroundColor: "rgba(212,160,21,0.1)"
    indicator: "3px gold left-border bar, rounded"
  stat-card-label:
    fontSize: "11px"
    textTransform: uppercase
    letterSpacing: "0.06em"
    textColor: "{colors.text-muted}"
  stat-card-value:
    fontFamily: "{typography.mono.fontFamily}"
    fontSize: "24px"
    fontWeight: 600
---

# TradingBot

## Overview

**Creative North Star:** Industrial precision meets luxury restraint. Every surface earned, every number exact. A Swiss watch control room built for one trader who demands the same craftsmanship from the interface as from the strategy.

**Product context:** Automated intraday equity trading bot for Indian market (NSE). Solo developer/trader tool. 5-page dashboard: Dashboard, Analysis, Trading, Settings, History. Competitors: TradingView (blue/teal), Zerodha Kite (green), Bloomberg (orange on black).

**Mode per surface:** Operate (all pages — task-driven monitoring and control)

**Reference sites:** TradingView, Zerodha Kite, Bloomberg Terminal, Stripe Dashboard (financial reporting reference)

**Key characteristics:**
- Premium dark: deep navy-black, not flat black — richer, easier on eyes over trading hours
- Gold accent: wealth/craftsmanship metaphor, distinct from category blues and greens
- Monospace financial data: every number in JetBrains Mono with tabular-nums
- Restrained color: color means state (profit/loss/active), never decoration
- Information density with breathing room: tight cards, generous section spacing

## Colors

**Strategy:** Restrained — gold accent + neutrals. Color is rare and meaningful.

**Dark-only:** Decided by the use scene — a trader watching screens for market hours, often in a dim room. Deep navy-black (#070a0f) is richer than pure black, easier on eyes, and works well on OLED.

The gold accent (#d4a015) is the brand color. It appears on the active nav indicator, primary buttons, chart accent lines, and the "running" pipeline state. Everything else is neutral. Green (#2da44e) and red (#f85149) are reserved strictly for profit/loss and success/error states. They never appear as decoration.

Surface hierarchy: background (#070a0f) < surface (#0f1419) < surface-elevated (#161d26). Borders (#1c2736) are always at reduced opacity (50%) to stay subtle.

## Typography

**Display — Satoshi (Fontshare).** Geometric modernist sans-serif by Indian Type Foundry. Its precision fits the "Swiss watch" thesis. Used sparingly: page titles only, at 20px bold. Never body text. Loading: preconnect to api.fontshare.com, swap display.

**Body/UI — Instrument Sans (Google Fonts).** Neo-grotesque with subtle playfulness. Clean at 13px for dense data tables and form labels. Allowed on Operate surfaces per the body/UI exception. 400/500/600 weights loaded.

**Mono/Numbers — JetBrains Mono (Google Fonts).** Purpose-built for code and data. `font-variant-numeric: tabular-nums` on every financial number — P&L, prices, quantities, percentages. This is the face traders see most; it must align in columns. 400/600 weights.

**Scale:** 11px labels (uppercase, tracked) / 13px body / 20px page titles / 24px stat values. No display type past 32px — this is a dashboard, not a poster.

## Layout

**Grid-disciplined.** 4-column stat grid, 2-column chart grid, 2-column position grid. Sidebar is 200px fixed. Content area has 24px padding.

**Density:** Tight within cards (16px padding), generous between sections (24-48px gap). Information density where it matters (numbers, tables), breathing room where it doesn't (section breaks, page titles).

**Max width:** None — fills available space. Trading dashboards benefit from horizontal room.

## Elevation & Depth

No shadows. Depth comes from surface color hierarchy (background < surface < surface-elevated) and border opacity. Zero-offset glows are banned. Hover states use surface-elevated background, not shadows.

## Shapes

**Radius hierarchy:** 4px (inputs, small controls) / 6px (buttons) / 8px (cards, sections) / 50% (dots, avatars). Nested inner radius = outer radius minus gap.

Pipeline step indicators: full circles (28px) with numbered content. Nav active indicator: 3px wide bar, rounded on the right side.

## Components

**Buttons:** Primary (solid gold, dark text), Danger (solid red, white text), Outline (border only), Save (gold tint background + gold text + gold border), Ghost (text only, hover changes color).

**Stat cards:** Uppercase label (11px, tracked, muted) above monospace number (24px, bold). Optional sub-line (11px, very muted) below. Card surface with 50%-opacity border.

**Pipeline stepper:** Vertical layout with numbered circles connected by a 1px line. Complete = green tint + checkmark. Active = gold tint + number + pulse. Pending = muted + number + 50% opacity. Cards expand on click when complete.

**Position cards:** Symbol + direction badge header. Label-value pairs in 2-column grid. Highlighted unrealised P&L in a tinted footer bar. Entry/LTP/Stop in monospace.

**Trade table:** Uppercase tracked column headers (10px). Hover rows. Direction column color-coded (green long, red short). P&L column in monospace, color-coded. No zebra stripes — hover is enough.

**Inputs:** Muted background, subtle border. Focus ring in gold at 50% opacity. Labels above in uppercase tracked micro-text.

## Do's and Don'ts

- Do: Use monospace tabular-nums for every number a trader compares
- Do: Reserve green/red strictly for profit/loss states
- Do: Keep labels uppercase, tracked, and muted — they recede behind the data
- Do: Use gold accent sparingly — nav indicator, primary actions, chart highlights
- Do: Show "No trades yet" for empty states, not blank space
- Don't: Add decorative elements, gradients, or blur effects
- Don't: Use color for decoration — color means state
- Don't: Put shadows on cards — use surface color hierarchy
- Don't: Animate continuously — brief 200ms flash for value changes only
- Don't: Use Satoshi for body text — it's display only at 20px+

## Motion

- **Approach:** Minimal-functional — only transitions that aid comprehension
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(100ms hover) short(150ms state) medium(200ms value flash)
- **The one authored moment:** Pipeline step transition from pending to active — the gold pulse dot draws the eye to where analysis is happening right now

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-09-25 | Initial design system created | Created by /design-consultation based on competitive research (TradingView, Kite, Bloomberg, Stripe) and product context (solo trader, NSE intraday bot) |
| 2026-09-25 | Gold accent (#d4a015) over blue/teal | Differentiates from TradingView (blue) and Kite (green); wealth/craftsmanship metaphor matches "wow factor" goal |
| 2026-09-25 | Satoshi + Instrument Sans + JetBrains Mono | Satoshi geometric precision for display, Instrument Sans clean at small sizes, JetBrains Mono tabular-nums for financial data |
| 2026-09-25 | Dark-only, no light mode | Use scene: trader watching screens for hours, often dim room. Deep navy-black over pure black for richness |
