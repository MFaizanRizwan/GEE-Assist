"""The IDW map's JavaScript (layer_map.html), run in Node.js against a stand-in Leaflet.

The real page needs Qt WebEngine and a display, which the tests do not have; Node runs its
script logic: Ctrl+click selection, highlighting, layer switches, and hiding / showing the
areas not selected (they must come back when switched on again).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_map_script_selects_hides_and_shows_areas():
    result = subprocess.run(["node", str(ROOT / "tests" / "js" / "layer_map_test.js"),
                             str(ROOT / "frontend" / "resources" / "layer_map.html")],
                            capture_output=True, text=True, timeout=60)
    assert "MAP LOGIC OK" in result.stdout, result.stdout + result.stderr
