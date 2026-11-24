"""A rotating-Earth loader, ported from GEE-Assist-Web (``EarthLoader``).

A shaded globe with the continents scrolling behind it (so it reads as turning) and a
satellite on a tilted orbit that passes behind the globe and back in front. Shown while
something slow runs — generating an AI explanation, or running an analysis.

It renders the same HTML/CSS/SVG as the website through Qt WebEngine (Chromium), tinted
with the current theme's colours. Where WebEngine is unavailable (or on the headless
"offscreen" platform used by the tests) it falls back to a label and an indeterminate bar,
so the page still works.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

from frontend import theme
from frontend import theming
from frontend.widgets.animated_svg import _web_engine_view_class  # platform/WebEngine probe

_LAND_PATH = (Path(__file__).resolve().parent.parent / "resources" / "earth_land_path.txt").read_text(
    encoding="utf-8"
)

# The loader page. Colours and text are substituted in build_html(); CSS braces are left as-is
# (no str.format), so tokens are @@NAME@@.
_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  :root {
    --ocean: @@OCEAN@@; --leaf: @@LEAF@@; --ink: @@INK@@;
    --muted: @@MUTED@@; --border: @@BORDER@@;
  }
  html, body { margin: 0; height: 100%; background: transparent; overflow: hidden; }
  body { display: flex; align-items: center; justify-content: center; }
  .earth-loader {
    display: flex; flex-direction: column; align-items: center; gap: 16px;
    padding: 20px; text-align: center; color: var(--muted);
    font-family: @@FONT@@; opacity: 0; transition: opacity .5s ease-out;
  }
  .earth-loader.in { opacity: 1; }
  .earth-loader-globe { position: relative; flex: none; isolation: isolate; }
  .earth-loader-globe svg { display: block; width: 100%; height: 100%; overflow: visible; position: relative; z-index: 1; }
  .earth-loader-glow { fill: none; stroke: var(--ocean); stroke-width: 3; opacity: .35; filter: blur(1.5px); }
  .earth-loader-land path { fill: #7cc58f; stroke: #5aa873; stroke-width: .4; stroke-linejoin: round; }
  .earth-loader-spin { animation: earth-turn 9s linear infinite; }
  .earth-loader-orbit { position: absolute; inset: 0 -16%; transform: rotate(-16deg); pointer-events: none; }
  .earth-loader-orbit.is-back { z-index: 0; clip-path: inset(0 0 50% 0); opacity: .55; }
  .earth-loader-orbit.is-front { z-index: 2; clip-path: inset(50% 0 0 0); }
  .earth-loader-ring {
    position: absolute; left: 0; right: 0; top: 50%;
    height: calc(var(--ry) * 2); margin-top: calc(var(--ry) * -1);
    border: 1px dashed color-mix(in srgb, var(--ocean) 60%, transparent); border-radius: 50%;
  }
  .earth-loader-sat-x {
    position: absolute; top: 50%; left: 0; right: 0; height: 0;
    animation: earth-x 1.7s ease-in-out infinite alternate;
  }
  .earth-loader-sat-x i {
    position: absolute; left: 50%; width: 14px; height: 7px; margin: -3.5px 0 0 -7px;
    border-radius: 2px; background: linear-gradient(90deg, #2f5f9e 0 34%, #d9ad4f 34% 66%, #2f5f9e 66%);
    box-shadow: 0 0 8px color-mix(in srgb, var(--leaf) 70%, transparent);
    animation: earth-y 1.7s ease-in-out -0.85s infinite alternate;
  }
  .earth-loader-text { display: grid; gap: 2px; }
  .earth-loader-text strong { font-size: 15px; font-weight: 600; color: var(--ink); }
  .earth-loader-text span { font-size: 13px; }
  @keyframes earth-turn { from { transform: translateX(0); } to { transform: translateX(200px); } }
  @keyframes earth-x { from { transform: translateX(-50%); } to { transform: translateX(50%); } }
  @keyframes earth-y { from { transform: translateY(calc(var(--ry) * -1)); } to { transform: translateY(var(--ry)); } }
  @media (prefers-reduced-motion: reduce) {
    .earth-loader-spin { animation-duration: 40s; }
    .earth-loader-sat-x, .earth-loader-sat-x i { animation: none; }
  }
</style></head>
<body>
  <div class="earth-loader" id="wrap">
    <div class="earth-loader-globe" style="width:@@SIZE@@px;height:@@SIZE@@px;">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <defs>
          <clipPath id="disc"><circle cx="50" cy="50" r="46"/></clipPath>
          <radialGradient id="sea" cx="38%" cy="32%" r="75%">
            <stop offset="0" stop-color="#3f8fd0"/><stop offset="0.6" stop-color="#1d5f97"/><stop offset="1" stop-color="#0c3559"/>
          </radialGradient>
          <radialGradient id="shade" cx="36%" cy="30%" r="72%">
            <stop offset="0" stop-color="#ffffff" stop-opacity="0.28"/>
            <stop offset="0.45" stop-color="#ffffff" stop-opacity="0"/>
            <stop offset="0.8" stop-color="#020c14" stop-opacity="0.35"/>
            <stop offset="1" stop-color="#020c14" stop-opacity="0.7"/>
          </radialGradient>
        </defs>
        <circle class="earth-loader-glow" cx="50" cy="50" r="48.5"/>
        <circle cx="50" cy="50" r="46" fill="url(#sea)"/>
        <g clip-path="url(#disc)">
          <g class="earth-loader-land" transform="translate(4 4) scale(0.92)">
            <g class="earth-loader-spin">
              <path d="@@LAND@@"/>
              <path d="@@LAND@@" transform="translate(-200 0)"/>
            </g>
          </g>
        </g>
        <circle cx="50" cy="50" r="46" fill="url(#shade)"/>
      </svg>
      <div class="earth-loader-orbit is-back" style="--ry:@@RY@@px;"><span class="earth-loader-ring"></span><span class="earth-loader-sat-x"><i></i></span></div>
      <div class="earth-loader-orbit is-front" style="--ry:@@RY@@px;"><span class="earth-loader-ring"></span><span class="earth-loader-sat-x"><i></i></span></div>
    </div>
    <div class="earth-loader-text"><strong id="lbl">@@LABEL@@</strong><span id="det">@@DETAIL@@</span></div>
  </div>
  <script>
    requestAnimationFrame(function () { document.getElementById('wrap').classList.add('in'); });
    function setText(l, d) {
      document.getElementById('lbl').textContent = l;
      var e = document.getElementById('det'); e.textContent = d || ''; e.style.display = d ? '' : 'none';
    }
  </script>
</body></html>"""


def build_html(label: str, detail: str, size: int) -> str:
    repl = {
        "@@OCEAN@@": theme.OCEAN, "@@LEAF@@": theme.LEAF, "@@INK@@": theme.INK,
        "@@MUTED@@": theme.MUTED, "@@BORDER@@": theme.BORDER,
        "@@FONT@@": f'"{theme.SANS}", "Segoe UI", sans-serif',
        "@@SIZE@@": str(size), "@@RY@@": f"{size * 0.19:.0f}",
        "@@LABEL@@": label, "@@DETAIL@@": detail, "@@LAND@@": _LAND_PATH,
    }
    page = _PAGE
    for token, value in repl.items():
        page = page.replace(token, value)
    return page


class EarthLoader(QWidget):
    """A turning globe with an orbiting satellite, shown while something slow runs.

    ``set_text(label, detail)`` updates the caption live. The widget animates only the
    globe/satellite; call it inside a busy state and hide it when the work is done.
    """

    def __init__(self, label: str = "Working…", detail: str = "", size: int = 128,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self._label = label
        self._detail = detail
        self._loaded = False
        self.setObjectName("EarthLoader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view = self._make_web_view()
        if self._view is not None:
            layout.addWidget(self._view)
        else:
            layout.addLayout(self._make_fallback())
        theming.on_theme_changed(self._retheme)  # recolour the globe page on a live theme change

    # ------------------------------------------------------------------ web backend
    def _make_web_view(self) -> QWidget | None:
        view_class = _web_engine_view_class()
        if view_class is None:
            return None
        try:
            view = view_class(self)
            view.page().setBackgroundColor(QColor(Qt.GlobalColor.transparent))
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            view.setMinimumHeight(self._size + 80)
            view.loadFinished.connect(self._on_loaded)
            view.setHtml(build_html(self._label, self._detail, self._size))
        except Exception:
            return None
        return view

    def _on_loaded(self, ok: bool) -> None:
        self._loaded = ok

    # ------------------------------------------------------------------ fallback
    def _make_fallback(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(10)
        self._fallback_label = QLabel(self._label)
        self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theming.styled(self._fallback_label, lambda: (
            f"font-family: '{theme.SERIF}'; font-size: 13pt; color: {theme.INK}; background: transparent;"
        ))
        self._fallback_detail = QLabel(self._detail)
        self._fallback_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theming.styled(self._fallback_detail, lambda: f"color: {theme.MUTED}; background: transparent;")
        bar = QProgressBar(objectName="BusyBar")
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedWidth(200)
        bar.setMaximumHeight(6)
        box.addWidget(self._fallback_label)
        box.addWidget(self._fallback_detail)
        box.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)
        return box

    # ------------------------------------------------------------------ public
    def _retheme(self) -> None:
        if self._view is not None:
            self._loaded = False
            self._view.setHtml(build_html(self._label, self._detail, self._size))

    def set_text(self, label: str, detail: str = "") -> None:
        self._label, self._detail = label, detail
        if self._view is not None:
            if self._loaded:
                self._view.page().runJavaScript(
                    f"setText({json.dumps(label)}, {json.dumps(detail)});"
                )
            else:
                QTimer.singleShot(60, lambda: self.set_text(label, detail))
        else:
            self._fallback_label.setText(label)
            self._fallback_detail.setText(detail)
