# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

Native Windows desktop app built with PyQt6 (Qt Widgets + Qt Style Sheets, Qt WebEngine for maps and animated SVG). None of web / ios / android applies: there is no browser page, HTML/CSS detector checks do not apply, and styling is QSS on Fusion.

## Users

Two audiences, served equally — neither should feel the app was made for the other:

- **Learners:** remote-sensing / GIS students and researchers who want Earth Engine data and analyses without writing GEE code. Final-year-project evaluators review the app in this role.
- **Practitioners:** GIS analysts who produce deliverables (downloads, indices, DEM/IDW surfaces, AI explanations, PDF reports) repeatedly and want speed.

## Product Purpose

GEE-Assist turns a plain request — a form or a natural-language sentence to Gemini — into Google Earth Engine downloads and local analyses: query → download → analyse → explain → report, inside projects. Success is a user getting from an area and a question to a saved, explained result without touching Earth Engine code.

## Positioning

Earth Engine's catalogue and compute, driven from a desktop app with a natural-language assistant, local GPU/CPU analyses, a built-in terminal (gkonsol), and per-project organisation — instead of the GEE Code Editor's JavaScript.

## Operating Context

- Users bring their own Earth Engine project ID and Gemini API key; sign-in goes through the GEE-Assist backend.
- Work is organised in projects (downloads, analysis results, reports per project).
- Pages: Dashboard, Query Input (parameter form + Gemini assistant + kept requests), Downloads, Data Catalog, Analysis, AI Explanation, Reports, Raster Viewer, Vector maps, DEM / terrain, IDW, Analysis table, Account, User admin; the gkonsol terminal docks under any page.
- Used in daytime labs and at demos as well as long evening analysis sessions.

## Capabilities and Constraints

- Three layouts (View → Layout): Layout 1 classical, Layout 2 modern (map-first), Layout 3 studio. Changing layout restarts the app; changing theme does not (live).
- Three themes: light, dark blue-green, dark grey. Every layout must work in all three; Layout 3 prioritises the dark themes.
- Layout 3 is the **power workspace**: dense, fast, many things visible at once, keyboard and terminal friendly.
- Layout 3 may rename, merge and regroup navigation and recompose every page, but every existing feature and workflow must keep working.
- Fonts bundled (as on GEE-Assist-Web): Sora (display), Work Sans (body), IBM Plex Mono (figures); golden-ratio type scale.

## Brand Commitments

- Name: GEE-Assist. Per-theme app icons exist in `assets/project_icon/`.
- A companion website (GEE-Assist-Web) shares the palette tokens; its solid, theme-reactive primary buttons are the reference the user made binding for button design.

## Evidence on Hand

Real datasets catalogue (`backend/config`), sample data in `sample_data/`, the intro video and Earth/satellite SVG in `assets/`. No user testimonials, usage metrics or benchmarks exist; none may be invented.

## Product Principles

1. Every feature reachable without code: the form, the assistant and the terminal are three doors to the same actions.
2. Projects are the unit of work; results always land somewhere the user can find again.
3. Experts and learners share one interface — density for the expert must never hide the path for the learner.
4. Long-running work (downloads, analyses, AI) always shows live progress and can be left and returned to.
