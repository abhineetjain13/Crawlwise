---
version: alpha
name: CrawlerAI
description: Deterministic crawl and extraction workspace with a dense, operator-first console UI and dual light/dark themes.
colors:
  primary: "#B85C38"
  accentWarm: "#E09A53"
  canvasLight: "#F6F1EA"
  canvasAltLight: "#EFE5D8"
  panelLight: "#FFF9F2"
  panelStrongLight: "#F4E8DA"
  borderLight: "#D8C8B8"
  borderStrongLight: "#CDB7A2"
  textPrimaryLight: "#2F241D"
  textSecondaryLight: "#5D4B40"
  textMutedLight: "#78665B"
  accentLight: "#B85C38"
  accentHoverLight: "#964728"
  accentSubtleLight: "#F5E1D2"
  onAccentLight: "#FFFFFF"
  successLight: "#3F7D48"
  warningLight: "#C67A2B"
  dangerLight: "#B44A3A"
  infoLight: "#C9874B"
  canvasDark: "#16110E"
  canvasAltDark: "#1F1814"
  panelDark: "#211A16"
  panelStrongDark: "#2A221D"
  borderDark: "#3A2F28"
  borderStrongDark: "#524137"
  textPrimaryDark: "#E6D8CB"
  textSecondaryDark: "#C6B29F"
  textMutedDark: "#9B8576"
  accentDark: "#D27A49"
  accentHoverDark: "#E09A53"
  accentSubtleDark: "#3B261D"
  onAccentDark: "#160F0B"
  successDark: "#62B26B"
  warningDark: "#E09A53"
  dangerDark: "#EF4444"
  infoDark: "#D59A68"
typography:
  heading1:
    fontFamily: Outfit
    fontSize: 1.5rem
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.02em
  heading2:
    fontFamily: Outfit
    fontSize: 1.25rem
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.02em
  heading3:
    fontFamily: Outfit
    fontSize: 1.125rem
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: -0.015em
  subheading:
    fontFamily: Outfit
    fontSize: 1rem
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: -0.005em
  body:
    fontFamily: Outfit
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0em
  bodySm:
    fontFamily: Outfit
    fontSize: 0.75rem
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0em
  control:
    fontFamily: Outfit
    fontSize: 0.875rem
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: 0em
  label:
    fontFamily: Outfit
    fontSize: 0.75rem
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: 0.05em
  labelMono:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: 0.05em
  caption:
    fontFamily: Outfit
    fontSize: 0.75rem
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: 0em
  captionMono:
    fontFamily: JetBrains Mono
    fontSize: 0.75rem
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: 0em
  metric:
    fontFamily: JetBrains Mono
    fontSize: 1.875rem
    fontWeight: 700
    lineHeight: 1
    letterSpacing: -0.02em
rounded:
  sm: 2px
  md: 3px
  lg: 4px
  xl: 6px
  xxl: 8px
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 20px
  xl: 24px
  xxl: 32px
  sidebar: 224px
  sidebarCollapsed: 72px
  topbar: 48px
  control: 32px
components:
  sidebarLight:
    backgroundColor: "{colors.canvasLight}"
    textColor: "{colors.textSecondaryLight}"
    rounded: "{rounded.xl}"
    width: "{spacing.sidebar}"
  sidebarDark:
    backgroundColor: "{colors.panelDark}"
    textColor: "{colors.textSecondaryDark}"
    rounded: "{rounded.xl}"
    width: "{spacing.sidebar}"
  topbarLight:
    backgroundColor: "{colors.panelLight}"
    textColor: "{colors.textPrimaryLight}"
    typography: "{typography.heading3}"
    height: "{spacing.topbar}"
    padding: "{spacing.xl}"
  topbarDark:
    backgroundColor: "{colors.panelStrongDark}"
    textColor: "{colors.textPrimaryDark}"
    typography: "{typography.heading3}"
    height: "{spacing.topbar}"
    padding: "{spacing.xl}"
  pageFrameLight:
    backgroundColor: "{colors.canvasAltLight}"
    textColor: "{colors.textPrimaryLight}"
    padding: "{spacing.xl}"
  pageFrameDark:
    backgroundColor: "{colors.canvasDark}"
    textColor: "{colors.textPrimaryDark}"
    padding: "{spacing.xl}"
  cardLight:
    backgroundColor: "{colors.panelLight}"
    textColor: "{colors.textPrimaryLight}"
    rounded: "{rounded.xxl}"
    padding: "{spacing.lg}"
  cardHeaderLight:
    backgroundColor: "{colors.panelStrongLight}"
    textColor: "{colors.textPrimaryLight}"
    typography: "{typography.subheading}"
    padding: "{spacing.md}"
  cardDark:
    backgroundColor: "{colors.panelDark}"
    textColor: "{colors.textPrimaryDark}"
    rounded: "{rounded.xxl}"
    padding: "{spacing.lg}"
  buttonPrimaryLight:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.onAccentLight}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  buttonPrimaryHoverLight:
    backgroundColor: "{colors.accentHoverLight}"
    textColor: "{colors.onAccentLight}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  buttonPrimaryDark:
    backgroundColor: "{colors.accentDark}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  buttonPrimaryHoverDark:
    backgroundColor: "{colors.accentWarm}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  buttonSecondaryLight:
    backgroundColor: "{colors.panelLight}"
    textColor: "{colors.textPrimaryLight}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  buttonSecondaryDark:
    backgroundColor: "{colors.panelStrongDark}"
    textColor: "{colors.textPrimaryDark}"
    typography: "{typography.control}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  inputLight:
    backgroundColor: "{colors.panelLight}"
    textColor: "{colors.textPrimaryLight}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  inputDark:
    backgroundColor: "{colors.panelStrongDark}"
    textColor: "{colors.textPrimaryDark}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    height: "{spacing.control}"
    padding: "{spacing.sm}"
  badgeAccentLight:
    backgroundColor: "{colors.accentSubtleLight}"
    textColor: "{colors.textPrimaryLight}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  badgeAccentDark:
    backgroundColor: "{colors.accentSubtleDark}"
    textColor: "{colors.textPrimaryDark}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  tableHeaderLight:
    backgroundColor: "{colors.canvasLight}"
    textColor: "{colors.textSecondaryLight}"
    typography: "{typography.labelMono}"
    padding: "{spacing.md}"
  tableHeaderDark:
    backgroundColor: "{colors.canvasAltDark}"
    textColor: "{colors.textSecondaryDark}"
    typography: "{typography.labelMono}"
    padding: "{spacing.md}"
  dividerLight:
    backgroundColor: "{colors.borderLight}"
    textColor: "{colors.textPrimaryLight}"
    height: 1px
    width: 100%
  dividerStrongLight:
    backgroundColor: "{colors.borderStrongLight}"
    textColor: "{colors.textPrimaryLight}"
    height: 1px
    width: 100%
  dividerDark:
    backgroundColor: "{colors.borderDark}"
    textColor: "{colors.textPrimaryDark}"
    height: 1px
    width: 100%
  dividerStrongDark:
    backgroundColor: "{colors.borderStrongDark}"
    textColor: "{colors.textPrimaryDark}"
    height: 1px
    width: 100%
  alertSuccessLight:
    backgroundColor: "{colors.successLight}"
    textColor: "{colors.onAccentLight}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  alertSuccessDark:
    backgroundColor: "{colors.successDark}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  alertWarningLight:
    backgroundColor: "{colors.warningLight}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  alertWarningDark:
    backgroundColor: "{colors.warningDark}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  alertDangerLight:
    backgroundColor: "{colors.dangerLight}"
    textColor: "{colors.onAccentLight}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  alertDangerDark:
    backgroundColor: "{colors.dangerDark}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.bodySm}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm}"
  badgeInfoLight:
    backgroundColor: "{colors.infoLight}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  badgeInfoDark:
    backgroundColor: "{colors.infoDark}"
    textColor: "{colors.onAccentDark}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  metadataLight:
    backgroundColor: "{colors.canvasLight}"
    textColor: "{colors.textMutedLight}"
    typography: "{typography.captionMono}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  metadataDark:
    backgroundColor: "{colors.canvasDark}"
    textColor: "{colors.textMutedDark}"
    typography: "{typography.captionMono}"
    rounded: "{rounded.md}"
    padding: "{spacing.xs}"
  metricPulseItemLight:
    backgroundColor: "{colors.panelLight}"
    textColor: "{colors.textPrimaryLight}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
  metricPulseItemDark:
    backgroundColor: "{colors.panelDark}"
    textColor: "{colors.textPrimaryDark}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
---

## Overview
CrawlerAI is an operator console, not a consumer app. The UI should feel precise, dense, calm, and slightly crafted. Take the scan discipline of an enterprise tool, then warm it up with terracotta accents, cream surfaces, and quieter contrast so long sessions feel less sterile.

Primary work happens in dashboards, crawl setup forms, tables, logs, and review panels. Interfaces should bias toward scan speed, clear state, and predictable alignment. Warmth should come from palette and depth, not ornament. The UI still serves operators first.

## Colors
The light theme uses warm mineral neutrals rather than office gray. `canvasLight` and `canvasAltLight` establish a cream-and-parchment shell. `panelLight` and `panelStrongLight` should feel like lifted paper and control trays, not cold white slabs. Text stays in roasted-brown neutrals, not black.

The primary accent is terracotta. Use `accentLight` or `accentDark` for primary actions, active navigation, focus rings, selected tabs, and thin emphasis lines. `accentWarm` is a support note for glow, progress warmth, or subtle highlight, not a second CTA system.

Dark theme stays warm and ember-like, not neon. It uses roasted charcoal surfaces, toasted borders, and copper accents. Dark panels should look fused, matte, and intentional.

Semantic colors are functional only. Success, warning, danger, and info exist to mark execution state, quality, and alerts. They should not become decorative accents.

## Typography
Use Outfit for all general UI copy. It gives the product a modern geometric voice without hurting density. Page titles, section headers, form controls, and descriptive text all stay in this family.

Use JetBrains Mono for values that operators compare, scan, or paste: metrics, run IDs, URLs, code blocks, logs, record counts, timestamps, table headers, and other machine-shaped text. Numeric surfaces should feel deliberate and tabular.

The hierarchy is shallow and practical:
- `heading1`, `heading2`, `heading3` for page and section structure
- `subheading` for card titles and grouped controls
- `body` and `caption` for explanation and metadata
- `label` and `labelMono` for uppercase field labels and table headers
- `metric` for KPI values and run counters

## Layout
The shell is fixed and operational. Sidebar width is `224px`, collapses to `72px`, and top bar height is `48px`. Main content sits inside a `1440px` frame with `24px` horizontal padding and consistent vertical stacks.

Default spacing rhythm is tight: `8px`, `12px`, `16px`, `24px`, `32px`. Prefer compact, repeatable spacing over loose hero-style whitespace. Dense does not mean cramped. Every panel should have enough internal air to keep table scans and form edits stable.

Pages are left-aligned and tool-like. Avoid centering whole workflows. The user should feel like they are operating a workspace, not reading a landing page.

## Elevation & Depth
Light theme uses warm borders first, tinted shadows second. Cards and toolbars get hairline structure plus a faint amber-brown lift only when separation helps. Surfaces should read stacked, not floating.

Dark theme compresses depth. Use merged surfaces, subtle tonal shifts, and ember-tinted shadows. The system should feel like one continuous workspace with controlled emphasis rather than layered glass.

Blur, gradients, grain, and motion are supporting effects only. Subtle parchment texture, radial warmth, and controlled glows can add polish, but they must stay background-level.

## Shapes
Radii are intentionally tight: `2px`, `3px`, `4px`, `6px`, `8px`. This is an industrial system. Edges should feel machined, not soft or playful.

Use small radii for controls and chips, larger radii for cards and panel groups. Reserve fully rounded shapes for dots, progress pills, scrollbar thumbs, and similar micro-signals.

## Components
Buttons are compact and task-driven. Primary buttons carry the terracotta accent and can take a warm glow on hover. Secondary buttons stay neutral and should sit comfortably inside dense toolbars without overpowering nearby data.

Cards and surface panels are the default containment unit. They usually have border-led separation, warm surface contrast, medium internal padding, and clear header/body structure. A card can carry a thin accent edge or top rule when it improves scan grouping.

Inputs and textareas should feel like stable data-entry fields: fixed control height, clear border, subtle elevation, strong focus ring, and no decorative fills.

Badges, status dots, and inline alerts are semantic instruments. They should communicate execution and review state fast, even in busy rows. Use tone plus wording; never tone alone. Warm neutrals are valid for passive metadata and inactive states.

Tables are core product UI. Headers should be uppercase, compact, and often mono. Row hover can pick up a faint terracotta wash or inset edge, but rows should not look clickable unless they actually are.

Metric pulse panels are the one place where the system can feel slightly more alive. Large mono values, a thin accent reveal, optional pulse behavior, and a warm highlight line are acceptable because they summarize runtime activity.

## Do's and Don'ts
Do use terracotta accent to mark action, focus, and active state.
Do use warm neutrals consistently across shell, panels, forms, and table surfaces.
Do use mono typography for metrics, logs, tables, URLs, and machine data.
Do keep labels uppercase and compact.
Do favor border-led separation, tinted shadows, and subtle texture.
Do preserve strong focus rings and keyboard-visible state.

Don't turn this into a marketing site.
Don't use oversized hero cards, oversized radii, or glossy AI gradients.
Don't center dashboards or forms that belong in a workspace flow.
Don't use semantic colors as decoration.
Don't hide critical state in color alone when text or icon support is available.
Don't reintroduce cool blue-gray palettes unless the product meaning demands it.
