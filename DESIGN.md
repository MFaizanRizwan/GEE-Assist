---
name: GEE-Assist
description: Earth Engine downloads and local GIS analyses from a PyQt6 desktop app; Layout 3 is the analyst's field book.
colors:
  field-book-yellow: "#E8B923"
  yellow-ink-light: "#8A6400"
  cover-dark-green: "#091516"
  cover-dark-grey: "#0C0C0C"
  cover-light: "#24282B"
  cover-raised-dark-green: "#1A2526"
  cover-raised-dark-grey: "#1D1D1D"
  cover-raised-light: "#33373A"
  cover-text: "#D3D7DA"
  cover-muted: "#A3AAB0"
  division-work: "#5DA9E9"
  division-work-ink: "#1F6FB2"
  division-analyse: "#6FCF97"
  division-analyse-ink: "#23845E"
  division-explain: "#B39DDB"
  division-explain-ink: "#6B4FA8"
  division-report: "#F2994A"
  division-report-ink: "#A8530F"
  on-division-dark: "#0F1416"
  accent-light: "#237D60"
  accent-light-hover: "#1B6650"
  accent-dark-green: "#5ED3A8"
  accent-dark-green-hover: "#86E3C1"
  accent-dark-grey: "#6FD6AE"
  accent-dark-grey-hover: "#95E4C5"
  on-accent-light: "#FFFFFF"
  on-accent-dark-green: "#0B1F21"
  on-accent-dark-grey: "#111111"
  page-dark-green: "#0F2224"
  surface-dark-green: "#173235"
  field-dark-green: "#12292B"
  ink-dark-green: "#EAF7F3"
  text-dark-green: "#CFE5E0"
  muted-dark-green: "#A3C2BC"
  border-dark-green: "#2B4D4E"
  border-strong-dark-green: "#3F6866"
  error-dark-green: "#FF8F80"
  page-dark-grey: "#141414"
  surface-dark-grey: "#1F1F1F"
  field-dark-grey: "#181818"
  ink-dark-grey: "#F2F2F2"
  text-dark-grey: "#D9D9D9"
  muted-dark-grey: "#ABABAB"
  border-dark-grey: "#333333"
  border-strong-dark-grey: "#4A4A4A"
  error-dark-grey: "#FF8A80"
  page-light: "#F2F8F6"
  surface-light: "#FFFFFF"
  field-light: "#FBFDFC"
  ink-light: "#1E3A3A"
  text-light: "#34504F"
  muted-light: "#6B8582"
  border-light: "#D3E4DF"
  border-strong-light: "#B9D3CC"
  error-light: "#C0392B"
typography:
  display:
    fontFamily: "Space Grotesk, Georgia"
    fontSize: "23pt"
  page-title:
    fontFamily: "Space Grotesk, Georgia"
    fontSize: "20pt"
    fontWeight: 600
  section-title:
    fontFamily: "Space Grotesk, Georgia"
    fontSize: "12.5pt"
    fontWeight: 600
  body:
    fontFamily: "Inter, Segoe UI"
    fontSize: "10pt"
    fontWeight: 400
  button:
    fontFamily: "Inter, Segoe UI"
    fontSize: "10.5pt"
    fontWeight: 600
  label:
    fontFamily: "Inter, Segoe UI"
    fontSize: "9.5pt"
    fontWeight: 600
  hint:
    fontFamily: "Inter, Segoe UI"
    fontSize: "8.5pt"
  warning:
    fontFamily: "Space Grotesk, Georgia"
    fontSize: "9.5pt"
    fontWeight: 600
  figure-large:
    fontFamily: "JetBrains Mono, Consolas"
    fontSize: "17pt"
  figure:
    fontFamily: "JetBrains Mono, Consolas"
    fontSize: "9pt"
  entry-number:
    fontFamily: "JetBrains Mono, Consolas"
    fontSize: "10pt"
    fontWeight: 600
  table-header:
    fontFamily: "Inter, Segoe UI"
    fontSize: "9pt"
    fontWeight: 600
rounded:
  checkbox: "4px"
  card: "6px"
  banner: "8px"
  field: "9px"
  button: "10px"
  auth-card: "18px"
spacing:
  module: "8px"
  tab-gap: "6px"
  stack: "16px"
  spread-gutter: "20px"
  page-x: "24px"
  page-y: "20px"
components:
  button-primary:
    backgroundColor: "{colors.accent-dark-green}"
    textColor: "{colors.on-accent-dark-green}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-dark-green-hover}"
  button-primary-light:
    backgroundColor: "{colors.accent-light}"
    textColor: "{colors.on-accent-light}"
    rounded: "{rounded.button}"
  button-primary-light-hover:
    backgroundColor: "{colors.accent-light-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-dark-green}"
    textColor: "{colors.ink-dark-green}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "10px 18px"
  division-tab:
    textColor: "{colors.muted-dark-green}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "5px 14px"
  division-tab-work-checked:
    backgroundColor: "{colors.division-work}"
    textColor: "{colors.on-division-dark}"
  side-index:
    backgroundColor: "{colors.cover-dark-green}"
    textColor: "{colors.cover-text}"
    height: "40px"
    width: "220px"
  side-index-current:
    backgroundColor: "{colors.cover-raised-dark-green}"
    textColor: "{colors.surface-light}"
  field-sheet:
    backgroundColor: "{colors.surface-dark-green}"
    rounded: "{rounded.card}"
  input:
    backgroundColor: "{colors.field-dark-green}"
    textColor: "{colors.ink-dark-green}"
    rounded: "{rounded.field}"
    padding: "9px 12px"
---

# Design System: GEE-Assist

## Overview

**Creative North Star: "The Survey Field Book"**

GEE-Assist is one PyQt6 desktop app with one shared design system (three live themes, one solid theme-reactive button accent, one button radius, three bundled faces) and three layouts built on it. Layout 1 (classical) and Layout 2 (modern, map-first) are structural variants of the shared base. Layout 3 ("studio") is a visual world of its own laid over that base: the analyst's field book. Every page is a ruled, indexed spread under a graphite cover with a yellow spine.

The field book lends exactly four things to the shared base, and only these: palette (graphite cover, field-book yellow, one hue per division), type (every figure in one measurement mono), density (24px page margins, ruled tables, the run log open), and the ruled 8px module drawn on the page ground. It never moves controls or changes what a page does. Result maps are the only full colour on the page; charts are drawn in yellow and muted ink.

Layout 3 is the power workspace and is dark-first: the dark blue-green and dark grey themes lead, and the light theme must hold. Depth is tonal and ruled, never lifted.

**Key Characteristics:**
- Graphite cover nav, darker than the page in every theme, with a 6px field-book-yellow spine on its right edge.
- Index numbers (Alt+1 to Alt+0, in page order) drawn in yellow mono where the nav icons would be.
- Four divisions (Work, Analyse, Explain, Report), each with one fixed hue: on the cover headings and on the checked division tab.
- Page ground ruled on an 8px hairline tile; flat sheets with 1px rules and a 6px corner.
- Yellow 1px rules under table headers, current-project rows and the spread's gutter.
- Every figure (counts, values, timings, paths, entry numbers) in JetBrains Mono.
- One solid button accent per theme, 10px radius, shared by all three layouts.

## Colors

A theme-reactive neutral base with one solid accent, over which Layout 3 adds a graphite cover, a single field-book yellow and four division hues.

### Primary
- **Field-Book Yellow** (field-book-yellow): the spine, the rule under table headers and section headers, the spread's gutter, the current nav item's border, progress chunks, index numbers on the cover, chart bars and lines, and entry numbers on dark pages. Constant across themes.
- **Pencil-Dark Yellow** (yellow-ink-light): the same yellow where it is text on a light page (entry numbers, the gkonsol prompt), darkened for legibility.
- **Theme Button Accent** (accent-light / accent-dark-green / accent-dark-grey): the solid fill of every primary button in every layout. The light theme uses its darker leaf because white on the standard leaf is about 3.5:1; the darker one is about 5:1. Hover goes to the paired hover token. Text on it is the theme's on-accent token.

### Secondary
- **Division Hues** (division-work, division-analyse, division-explain, division-report): Data blue, Analyse green, Explain violet, Report orange. Dark themes take the light tints; the light theme takes the ink variants (division-*-ink), which are text-safe on white. On the graphite cover the light tints are used in every theme, because the cover stays dark. A checked division tab fills with its hue and sets text in on-division-dark (dark themes) or white (light theme).

### Neutral
- **Graphite Cover** (cover-dark-green / cover-dark-grey / cover-light): the nav's ground. In dark themes it is the page colour mixed 38% toward black; over the light theme it is a fixed graphite. Hover and current items sit on cover-raised (cover mixed 7% toward white).
- **Cover Text / Cover Muted** (cover-text, cover-muted): nav labels and secondary nav text, and the nav's painted icons.
- **Page, Surface, Field** (page-*, surface-*, field-*): the page ground behind the ruled tile, the sheets and cards on it, and input wells. The palette key for surface is historically named WHITE in every theme.
- **Ink, Text, Muted** (ink-*, text-*, muted-*): headings and values, body copy, captions and table headers.
- **Border, Border Strong** (border-*, border-strong-*): 1px sheet outlines and table rules; input and secondary-button outlines. The 8px grid line is the page colour mixed 55% toward border.
- **Error** (error-*): field errors, danger buttons and error banners, with matching ERROR_BG / ERROR_BORDER tints in `frontend/palette.py`.

### Named Rules
**The One Yellow Rule.** Field-book yellow is the only accent the field book adds. It rules, it numbers, it marks progress; it is never a button fill and never a large area.

**The Maps Are The Colour Rule.** In Layout 3 the result maps are the only full-colour surfaces. Charts use yellow and muted ink; division hues appear only on headings and the checked tab.

**The One Accent Rule.** Every primary button in every layout is the active theme's solid accent. Layouts differ in structure and surfaces, never in button hue.

## Typography

**Display Font:** Space Grotesk (falls back to Georgia)
**Body Font:** Inter (falls back to Segoe UI)
**Label/Mono Font:** JetBrains Mono (falls back to Consolas)

All three are bundled in `frontend/resources/fonts/` and registered at start-up; glyphs they lack fall back to Segoe UI, Segoe UI Symbol and Segoe UI Emoji. Sizes are in points because Qt Style Sheets set them in points.

**Character:** a geometric display face with real character for headings and warnings, a quiet body face for dense controls, and one measurement mono for every number, so a field book's figures line up and read as data.

### Hierarchy
- **Display** (Space Grotesk, 23pt): the sign-in title.
- **Page Title** (Space Grotesk 600, 20pt): the project name or page name at the top of each page.
- **Section Title** (Space Grotesk 600, 12.5pt): sheet and section headings ("At a glance", "Recent analysis results").
- **Body** (Inter 400, 10pt): all controls and paragraphs; the app default font.
- **Button** (Inter 600, 10.5pt): every push button.
- **Label** (Inter 600, 9.5pt): field labels, in ink.
- **Hint** (Inter, 8.5pt): field hints, in the subtle colour.
- **Warning** (Space Grotesk 600, 9.5pt banners; 8.5pt field errors): error, success and info banners and field errors, set apart from body text.
- **Table Header** (Inter 600, 9pt, muted): table column headers over a yellow rule.
- **Figure Large** (JetBrains Mono, 17pt): glance values and stat values.
- **Figure** (JetBrains Mono, 9pt): paths, sizes, ETAs, table values and timings.
- **Entry Number** (JetBrains Mono 600, 10pt, yellow): zero-padded entry numbers in ruled tables; index numbers in the nav (10pt bold).

### Named Rules
**The One Measurement Face Rule.** In Layout 3 every figure is JetBrains Mono. A number set in Inter is a defect.

## Layout

The window is a nav column on the left, the pages on the right, and the gkonsol terminal docked along the foot. In Layout 3 the nav opens expanded (220px, collapsing to an 77px logo rail; it slides over 220ms on an OutCubic curve), a division strip sits above every page (24px side margins, 10px top, 8px bottom, 6px between tabs), and the run log is open by default. `CHROME_HEIGHT` (160px) reserves the strip and the open run log around each page.

Page content uses 24px horizontal and 20px vertical margins in Layout 3, with 16px between stacked blocks. The page ground carries an 8x8 tile with one hairline on its right and bottom edge, repeated: the visible 8px module. Measurements on the page are multiples of 4 and mostly of 8.

The Dashboard's signature arrangement is the spread: one bound sheet holding a left page (ruled results table and recent projects) and a right page (result maps and charts), separated by a 20px gap and the right page's 1px yellow left border (the gutter). The glance row is a set of transparent tiles divided by 1px vertical rules.

Navigation order is the index: Work (Dashboard, Query Input, Downloads, Data Catalog), Analyse (Analysis, Vector Maps, Elevation, IDW), Explain (AI Explanation), Report (Reports), then Tools (Terminal, Manage users) with no index.

## Elevation & Depth

Layout 3 is flat. Depth is carried by tone (the cover darker than the page, the page darker than its sheets in dark themes) and by 1px rules, not by shadows. The shared base has one soft shadow, used only on the sign-in card and the account card in every layout.

### Shadow Vocabulary
- **Soft Lift** (`QGraphicsDropShadowEffect`, blur 48, y-offset 12, SHADOW colour at alpha 34): the floating sign-in and account cards only.

### Named Rules
**The Ruled Not Lifted Rule.** Field-book sheets never cast shadows. Separation is a 1px border or a yellow rule.

## Shapes

Two radii carry the system. Buttons and division tabs have a 10px radius everywhere. Layout 3's sheets and cards are cut nearly square at 6px. Inputs, spin boxes and combo boxes have a 9px radius; banners and menus 8px; checkboxes 4px; the sign-in card 18px. Ruled rows, glance tiles and section headers have no radius and draw only a bottom or right 1px line. Collapsed nav buttons are circles (40px wide and high, radius 20px).

### Named Rules
**The Half-Height Rule.** Qt ignores a border-radius larger than half a widget's height and draws square corners instead. Buttons keep `BUTTON_RADIUS` (10px); never raise it.

## Components

### Buttons
Solid, theme-reactive and confident, matching the companion website.
- **Shape:** gently rounded (10px), padding 10px 18px (9px 22px on the query form).
- **Primary:** the theme's solid accent with its on-accent text, no border.
- **Hover / Pressed:** fill darkens to the hover token. Pressed shifts padding 1px down (Qt has no transforms or transitions). Disabled uses PRIMARY_DISABLED_FROM with PRIMARY_DISABLED_TEXT.
- **Secondary:** surface fill, ink text, 1px border-strong outline; hover fills FOAM with an ink border; pressed fills MINT.
- **Danger:** surface fill, error text, 1px ERROR_BORDER outline; hover fills ERROR_BG.
- **Link:** transparent, OCEAN text, underline on hover.

### Division Tabs (Layout 3)
- **Style:** transparent, muted text, 1px rule-colour outline, 10px radius, 5px 14px padding, Inter 600.
- **Hover:** ink text, BORDER_HOVER outline.
- **Checked:** filled with the division's hue, text on-division-dark (dark themes) or white (light theme). Clicking a tab opens its division's first page.

### Cards / Containers
- **Corner Style:** 6px in Layout 3.
- **Background:** the theme surface.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** 1px theme border.
- **Internal Padding:** 18px 16px for panels; 24px 20px for the spread's pages.

### Ruled Tables (Layout 3)
- **Header:** transparent, muted Inter 600 9pt, 6px 8px padding, 1px yellow bottom rule.
- **Rows:** transparent, 4px 6px padding, 1px border-colour bottom rule per row, no grid boxes.
- **Columns:** the results table runs #, Analysis, Dataset, When, Result, Run. Entry numbers are zero-padded mono in yellow (pencil-dark yellow in the light theme); values, dates and timings are mono.

### Inputs / Fields
- **Style:** field-colour well, 1px border-strong outline, 9px radius, 9px 12px padding (6px 11px on the form), ink text.
- **Hover:** BORDER_HOVER outline.
- **Focus:** 1.5px LEAF outline, surface fill.
- **Error / Disabled:** 1.5px error outline on ERROR_FIELD_BG; disabled text in subtle on DISABLED_BG.

### Navigation (Layout 3 index)
- **Style:** the graphite cover, with a 6px yellow right border as the spine. Buttons 40px high, 8px radius, Inter 500 in cover text.
- **Index:** each page button paints its Alt shortcut number (JetBrains Mono bold 10pt, yellow) where the icon would be. Tools carry no number.
- **Division headings:** Inter 600 9pt in the division's cover hue, 12px top padding.
- **Hover:** cover-raised fill. **Current:** cover-raised fill, 1px yellow border, white text, weight 600.

### Run Log (gkonsol)
Docked under every page and open by default in Layout 3. JetBrains Mono, recoloured live with the theme; warnings in amber per theme (#9A6700 light, #F2C46D dark blue-green, #F0C674 dark grey); the prompt in field-book yellow in Layout 3 (the theme leaf elsewhere).

### Glance Row
Five counts (Downloads, Analyses run, Saved result maps, AI explanations, PDF reports): a 17pt mono value over a muted Inter caption, in transparent tiles divided by 1px vertical rules.

## Do's and Don'ts

### Do:
- **Do** build every theme-dependent stylesheet through `theming.styled(widget, builder)`, with a builder that reads current theme values, so it recolours live. Painter-drawn widgets read `theme.*` at paint time; subscribe anything else with `theming.on_theme_changed`.
- **Do** expect a theme change to apply live and a layout change to restart the app; read `fieldbook.active()` once.
- **Do** keep every button at `BUTTON_RADIUS` (10px) and every primary button on the theme's solid accent.
- **Do** set every figure in JetBrains Mono in Layout 3.
- **Do** mark division with the division strip and the side index, and number entries in yellow.
- **Do** use the ink variants of division hues on the light theme, and pencil-dark yellow (yellow-ink-light) where yellow is text on a light page.
- **Do** check every new Layout 3 surface in all three themes, dark first.

### Don't:
- **Don't** raise a button radius above half its height: Qt draws square corners instead.
- **Don't** rely on a QLabel bottom border to mark a page title or section: it does not paint reliably. Use the division strip and the side index, or a QFrame rule.
- **Don't** set a stylesheet with a one-off `setStyleSheet(f"...")` that reads theme colours: it freezes on the theme it was built in.
- **Don't** add shadows to Layout 3 sheets or cards.
- **Don't** fill buttons or large areas with field-book yellow, and don't give charts or chrome full colour in Layout 3: result maps carry the colour.
- **Don't** use a division hue outside its own division's heading and tab.
- **Don't** set figures in Inter or the display face in Layout 3.
