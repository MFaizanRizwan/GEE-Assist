"""The web maps on a real screen (opt-in: needs a display, Qt WebEngine and internet).

    set GEE_LIVE_MAPS=1 && python -m pytest tests/test_live_maps.py

Replays what froze the IDW map: points and boundaries on it, then hidden (Picture, another
page) and shown again. The page must keep painting and answering.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, os.getcwd())
import PyQt6.QtWebEngineWidgets  # noqa: F401  (before the application, as the app does)
from PyQt6.QtWidgets import QApplication, QStackedWidget, QLabel
from PyQt6.QtTest import QTest
app = QApplication(sys.argv)
from frontend.widgets.layer_map_widget import LayerMapWidget, boundaries_geojson
from backend.business.vector import VectorService
stack = QStackedWidget(); world = LayerMapWidget(); stack.addWidget(world); stack.addWidget(QLabel("picture"))
stack.resize(800, 500); stack.show()
page = world._view.page()
def js(expr, timeout=5):
    got = []; page.runJavaScript(expr, lambda v: got.append(v)); t = time.time()
    while not got and time.time() - t < timeout: QTest.qWait(30)
    return got[0] if got else None
t0 = time.time()
while not world._ready and time.time() - t0 < 30: QTest.qWait(100)
assert world._ready, "the map page never loaded"
world.set_points([(73.0 + i * 0.01, 31.4, f"p{i}") for i in range(60)])
world.fit((72.5, 31.0, 73.6, 31.9)); QTest.qWait(1200)
for _ in range(3):
    stack.setCurrentIndex(1); QTest.qWait(400); stack.setCurrentIndex(0); QTest.qWait(1200)
    assert js("1+1") == 2, "the map froze after being shown again"
print("LIVE MAP OK")
'''


@pytest.mark.skipif(os.environ.get("GEE_LIVE_MAPS") != "1" or sys.platform != "win32",
                    reason="opt-in: needs a display, Qt WebEngine and internet (GEE_LIVE_MAPS=1)")
def test_the_idw_map_survives_being_hidden_and_shown():
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert "LIVE MAP OK" in result.stdout, result.stdout[-2000:] + result.stderr[-2000:]
