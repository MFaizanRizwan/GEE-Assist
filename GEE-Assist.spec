# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for GEE-Assist. Run through build_app.py, not directly.

build_app.py stages main.py, frontend/ (source) and the Cython-compiled backend/
(.pyd only) in build/app_stage/, then runs this file.

One-folder build, not one-file. A one-file .exe unpacks about 6,000 files
(~1 GB) into %TEMP% on every start, and Microsoft Defender scans each of them
every time: that is the high Defender CPU use and the slow start. In one folder
the files are unpacked once, when the user extracts the zip, and Defender's
scan results are cached after the first run.

UPX is off: UPX-packed files are a common reason for antivirus false positives.
"""

import ast
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata
from PyInstaller.utils.win32 import versioninfo as vi

ROOT = Path(SPECPATH).resolve()
STAGE = ROOT / "build" / "app_stage"
APP_VERSION = "1.0.0"
for line in (ROOT / "backend" / "config" / "version.py").read_text(encoding="utf-8").splitlines():
    if line.startswith("APP_VERSION"):
        APP_VERSION = line.split("=", 1)[1].strip().strip("\"'")


def backend_modules():
    """Every compiled backend module, by dotted name."""
    names = set()
    for path in (STAGE / "backend").rglob("*"):
        if path.suffix not in (".pyd", ".py"):
            continue
        parts = list(path.relative_to(STAGE).parts)
        parts[-1] = parts[-1].split(".")[0]
        if parts[-1] == "__init__":
            parts.pop()
        names.add(".".join(parts))
    return names


def backend_imports():
    """What the backend imports. PyInstaller cannot read imports out of a .pyd,
    so they are taken from the Python source instead."""
    names = set()
    for path in (ROOT / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
    optional = {"cupy"}  # GPU support, only used when the user installs it
    return {n for n in names if n.split(".")[0] not in optional | {"__future__", "backend"}}


hiddenimports = sorted(backend_modules() | backend_imports())
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("rasterio")

datas = [
    (str(ROOT / "frontend" / "resources"), "frontend/resources"),
    (str(ROOT / "docs" / "GKONSOL.md"), "docs"),
]
for path in (ROOT / "assets").rglob("*"):
    rel = path.relative_to(ROOT)
    if path.is_file() and rel.parts[1] != "tmp":
        datas.append((str(path), str(rel.parent)))

# rasterio's projection database (proj.db) and GDAL's data files. rasterio
# looks for them beside its own package; without them every analysis fails
# with "PROJ: proj_create_from_database: Cannot find proj.db".
datas += collect_data_files("rasterio", includes=["proj_data/**/*", "gdal_data/**/*"])

binaries = []
for package in ("en_core_web_sm", "spacy", "thinc", "ee", "google.genai", "markdown_pdf", "pymupdf"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
# Package versions read at run time (gkonsol's "version" command, spaCy's model check).
for dist in ("earthengine-api", "google-genai", "spacy", "en_core_web_sm", "keyring", "rasterio", "numpy"):
    datas += copy_metadata(dist)

a = Analysis(
    [str(STAGE / "main.py")],
    pathex=[str(STAGE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "Cython", "pytest", "_pytest", "IPython", "matplotlib", "PyQt5", "PySide6", "cupy"],
    noarchive=False,
)


def unwanted(dest):
    dest = dest.replace("\\", "/")
    return (
        # ~110 MB of Google API descriptions. Earth Engine fetches its own at run
        # time (static_discovery=False), so these are never read.
        "googleapiclient/discovery_cache/documents/" in dest
        # ~87 MB, only used by Chromium's developer tools.
        or "qtwebengine_devtools_resources" in dest
    )


a.datas = [entry for entry in a.datas if not unwanted(entry[0])]
a.binaries = [entry for entry in a.binaries if not unwanted(entry[0])]

pyz = PYZ(a.pure)

numbers = tuple(int(p) for p in (APP_VERSION.split(".") + ["0"] * 4)[:4])
version = vi.VSVersionInfo(
    ffi=vi.FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        vi.StringFileInfo([vi.StringTable("040904B0", [
            vi.StringStruct("CompanyName", "GEE-Assist"),
            vi.StringStruct("FileDescription", "GEE-Assist"),
            vi.StringStruct("FileVersion", APP_VERSION),
            vi.StringStruct("InternalName", "GEE-Assist"),
            vi.StringStruct("OriginalFilename", "GEE-Assist.exe"),
            vi.StringStruct("ProductName", "GEE-Assist"),
            vi.StringStruct("ProductVersion", APP_VERSION),
        ])]),
        vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GEE-Assist",
    icon=str(ROOT / "assets" / "app.ico"),
    version=version,
    console=False,
    upx=False,
    debug=False,
    strip=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="GEE-Assist", upx=False, strip=False)
