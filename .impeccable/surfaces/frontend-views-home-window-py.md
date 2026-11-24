---
version: 1
slug: "frontend-views-home-window-py"
primary_target: "frontend/views/home_window.py"
related_targets: ["frontend/form_theme.py","frontend/views/dashboard_view.py","frontend/widgets/side_bar.py"]
---

## Scope

Layout 3 ("studio") of the GEE-Assist PyQt6 desktop app, applied to the whole signed-in window: shell, side navigation, every page (Dashboard first), the query form, and the gkonsol run log. Mode: Operate. Users: learners and practitioners equally; power-workspace density; dark themes first, light theme must hold.

## Direction contract

THESIS: Layout 3 is the analyst's field book: every page is a ruled, indexed spread under a graphite cover with a yellow spine. It refuses the category default of grey dockable panels with one blue accent.

OWN-WORLD: graphite cover darker than the theme ground; a 6px field-book-yellow spine on the navigation; pages ruled on a faint 8px module; yellow rules under table and section headers; red pencil (theme error colour, struck through) for failures; one fixed hue per division (Data blue, Analyse green, Explain violet, Report orange); every figure in one measurement mono; result maps are the only full colour. Buttons are the theme accent at a 10px radius.

STORY: the user always knows the division and page they are on, scans dense records at a glance, jumps anywhere with Ctrl+number, and watches live work in the run log.

FIRST VIEWPORT: Dashboard. Left: 232px spine nav in three divisions, each page with its Ctrl shortcut number. Top: project name as the heading, division tab, Open / Create project. A ruled glance row (Downloads, Analyses run, Saved result maps). The spread: left page lists recent analysis results and recent projects in ruled tables with entry numbers; right page shows the newest result map. Run log (gkonsol) docked along the foot.

FORM: Survey Field Book, position 7 of the ordered list; seed:1d2b2b953656008d. Raises: visible 8px module (Crouwel grid), maps as the only colour (title-card wall), one hue per division (acetate manual), one measurement face on a strict scale (bitmap specimen).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
