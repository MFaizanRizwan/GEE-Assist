"""Colour palettes of the app's themes (light, dark blue-green, dark grey), in one place.

``theme`` and ``form_theme`` take their colours from ``ACTIVE``, the saved theme's
palette. The names come from the light theme: ``WHITE`` is the colour of cards and
surfaces, ``INK`` the strongest text, ``LEAF`` / ``OCEAN`` the green and blue accents;
a dark palette gives each name its dark-theme colour.
"""

from __future__ import annotations

import os

from frontend import appearance

LIGHT: dict[str, str] = {
    # surfaces and text
    "WHITE": "#FFFFFF",
    "INK": "#1E3A3A",            # headings / main text: deep green-slate
    "TEXT": "#34504F",
    "MUTED": "#6B8582",
    "SUBTLE": "#93A9A6",
    "BORDER": "#D3E4DF",
    "BORDER_STRONG": "#B9D3CC",
    "BORDER_HOVER": "#9CC5BA",
    "FIELD_BG": "#FBFDFC",
    "DISABLED_BG": "#F3F6F5",
    # accents
    "LEAF": "#2E9E78",           # primary green
    "LEAF_DARK": "#237D60",
    "OCEAN": "#2F7FC1",          # primary blue
    "OCEAN_DARK": "#24659C",
    "MINT": "#EAF6F0",
    "SKY": "#E6F1FA",
    "FOAM": "#F4FAF8",
    # pages and section headers
    "PAGE_BG": "#F2F8F6",        # soft green-blue page behind the white cards
    "HEADER_GREEN": "#DFF1E8",   # section header band: light sage-green ...
    "HEADER_BLUE": "#DFEDF7",    # ... fading to a light sky-blue
    "HEADER_LINE": "#C4E0D5",
    # messages
    "ERROR": "#C0392B",
    "ERROR_BG": "#FDF1EF",
    "SUCCESS": "#23845E",
    "SUCCESS_BG": "#ECF7F1",
    "INFO_BG": "#EEF5FB",
    "ERROR_BORDER": "#F3C9C3",
    "SUCCESS_BORDER": "#BFE3D1",
    "INFO_BORDER": "#C9DFF1",
    "ERROR_FIELD_BG": "#FFFBFA",   # a field with an invalid value
    # primary buttons (solid: see accent.py) and their disabled state
    "PRIMARY_TEXT": "#FFFFFF",
    "PRIMARY_DISABLED_TEXT": "#F2F7F6",
    "PRIMARY_DISABLED_FROM": "#8CCBB6",
    "PRIMARY_DISABLED_TO": "#92BCE0",
    # button accent (primary buttons, checked segments, mode switcher): each theme has its
    # OWN hue so switching theme visibly recolours the buttons. Light = green → blue.
    "ACCENT_FROM": "#2E9E78",
    "ACCENT_TO": "#2F7FC1",
    "ACCENT_FROM_HOVER": "#237D60",
    "ACCENT_TO_HOVER": "#24659C",
    "ACCENT_TEXT": "#FFFFFF",       # text/icon on the accent gradient
    "ACCENT_SOFT": "#EAF6F0",       # faint accent tint (hover fills, selection)
    "OPEN_BUTTON_TOP": "#4CB98E",  # "open folder" button: gradient into LEAF
    # signed-in pages: background gradient
    "PAGE_GRADIENT_TOP": "#F3FAF6",
    "PAGE_GRADIENT_MIDDLE": "#F2F8FB",
    "PAGE_GRADIENT_BOTTOM": "#ECF4FB",
    # sign-in picture panel: background gradient
    "HERO_TOP": "#EEF8F2",
    "HERO_MIDDLE": "#EAF4F8",
    "HERO_BOTTOM": "#E2EEF9",
    # pieces of particular screens
    "TILE_DISABLED_BG": "#FAFCFB",  # "coming soon" dashboard cards
    "PROGRESS_TRACK": "#E4EEEB",
    "PROGRESS_PAUSED": "#9DB8B2",
    "PROGRESS_FAILED": "#E3A79F",
    "TABLE_LINE": "#EDF3F1",
    "CHART_GRID": "#E3EEEA",
    "SHADOW": "#1E5A57",
    "SPLASH_BG": "#FFFFFF",         # the intro video has a white background in every theme
    "BUTTON": "#237D60",            # the solid button fill (accent.py)
    "BUTTON_HOVER": "#1B6650",
}


# Dark themes: dark surfaces with light, high-contrast text, borders and accents.
# Gradient (primary) buttons use the light accents with dark text on them.
DARK_GREEN: dict[str, str] = {   # deep blue-green
    "WHITE": "#173235",
    "INK": "#EAF7F3",
    "TEXT": "#CFE5E0",
    "MUTED": "#A3C2BC",
    "SUBTLE": "#80A39D",
    "BORDER": "#2B4D4E",
    "BORDER_STRONG": "#3F6866",
    "BORDER_HOVER": "#5E8C88",
    "FIELD_BG": "#12292B",
    "DISABLED_BG": "#1C3436",
    "LEAF": "#5ED3A8",
    "LEAF_DARK": "#86E3C1",
    "OCEAN": "#6CB8F0",
    "OCEAN_DARK": "#93CCF6",
    "MINT": "#21403F",
    "SKY": "#1C3448",
    "FOAM": "#1E3B3C",
    "PAGE_BG": "#0F2224",
    "HEADER_GREEN": "#1D3D39",
    "HEADER_BLUE": "#1B3445",
    "HEADER_LINE": "#2F5552",
    "ERROR": "#FF8F80",
    "ERROR_BG": "#3A2224",
    "SUCCESS": "#72DFB2",
    "SUCCESS_BG": "#163A2E",
    "INFO_BG": "#172F42",
    "ERROR_BORDER": "#6B3A37",
    "SUCCESS_BORDER": "#2E6650",
    "INFO_BORDER": "#2E5677",
    "ERROR_FIELD_BG": "#2C1E20",
    "PRIMARY_TEXT": "#0B1F21",
    "PRIMARY_DISABLED_TEXT": "#5E7C79",
    "PRIMARY_DISABLED_FROM": "#2B4F47",
    "PRIMARY_DISABLED_TO": "#2B4659",
    # Dark blue-green theme: accent is a bright teal → cyan, distinct from the light theme.
    "ACCENT_FROM": "#2FD1C4",
    "ACCENT_TO": "#38C6E8",
    "ACCENT_FROM_HOVER": "#55E0D5",
    "ACCENT_TO_HOVER": "#63D5F0",
    "ACCENT_TEXT": "#06201E",       # dark text reads on the bright accent
    "ACCENT_SOFT": "#17383A",
    "OPEN_BUTTON_TOP": "#86E3C1",
    "PAGE_GRADIENT_TOP": "#0F2426",
    "PAGE_GRADIENT_MIDDLE": "#0F2229",
    "PAGE_GRADIENT_BOTTOM": "#0E1F2B",
    "HERO_TOP": "#12302A",
    "HERO_MIDDLE": "#122B33",
    "HERO_BOTTOM": "#13263A",
    "TILE_DISABLED_BG": "#142A2C",
    "PROGRESS_TRACK": "#24403F",
    "PROGRESS_PAUSED": "#7A9C96",
    "PROGRESS_FAILED": "#D08378",
    "TABLE_LINE": "#22403F",
    "CHART_GRID": "#264544",
    "SHADOW": "#000000",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#5ED3A8",            # the solid button fill (accent.py)
    "BUTTON_HOVER": "#86E3C1",
}

DARK_GREY: dict[str, str] = {    # plain black and grey
    "WHITE": "#1F1F1F",
    "INK": "#F2F2F2",
    "TEXT": "#D9D9D9",
    "MUTED": "#ABABAB",
    "SUBTLE": "#8A8A8A",
    "BORDER": "#333333",
    "BORDER_STRONG": "#4A4A4A",
    "BORDER_HOVER": "#6B6B6B",
    "FIELD_BG": "#181818",
    "DISABLED_BG": "#262626",
    "LEAF": "#6FD6AE",
    "LEAF_DARK": "#95E4C5",
    "OCEAN": "#7DBDF2",
    "OCEAN_DARK": "#A3D0F6",
    "MINT": "#303030",
    "SKY": "#2A2F35",
    "FOAM": "#2A2A2A",
    "PAGE_BG": "#141414",
    "HEADER_GREEN": "#262626",
    "HEADER_BLUE": "#2B2B2B",
    "HEADER_LINE": "#3A3A3A",
    "ERROR": "#FF8A80",
    "ERROR_BG": "#3A2323",
    "SUCCESS": "#7EDDB6",
    "SUCCESS_BG": "#1E3329",
    "INFO_BG": "#1E2A35",
    "ERROR_BORDER": "#663535",
    "SUCCESS_BORDER": "#335C48",
    "INFO_BORDER": "#334D66",
    "ERROR_FIELD_BG": "#2A1F1F",
    "PRIMARY_TEXT": "#111111",
    "PRIMARY_DISABLED_TEXT": "#6E6E6E",
    "PRIMARY_DISABLED_FROM": "#383838",
    "PRIMARY_DISABLED_TO": "#3D3D3D",
    # Dark grey theme: accent is a violet → magenta, a clear third hue.
    "ACCENT_FROM": "#9B7BF0",
    "ACCENT_TO": "#E267C9",
    "ACCENT_FROM_HOVER": "#AE92F4",
    "ACCENT_TO_HOVER": "#EC82D4",
    "ACCENT_TEXT": "#15101E",        # dark text for contrast on the bright accent
    "ACCENT_SOFT": "#2A2433",
    "OPEN_BUTTON_TOP": "#95E4C5",
    "PAGE_GRADIENT_TOP": "#151515",
    "PAGE_GRADIENT_MIDDLE": "#161616",
    "PAGE_GRADIENT_BOTTOM": "#181818",
    "HERO_TOP": "#1B1B1B",
    "HERO_MIDDLE": "#1D1D1D",
    "HERO_BOTTOM": "#202020",
    "TILE_DISABLED_BG": "#1A1A1A",
    "PROGRESS_TRACK": "#2E2E2E",
    "PROGRESS_PAUSED": "#8F8F8F",
    "PROGRESS_FAILED": "#D08A80",
    "TABLE_LINE": "#2C2C2C",
    "CHART_GRID": "#2E2E2E",
    "SHADOW": "#000000",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#6FD6AE",            # the solid button fill (accent.py)
    "BUTTON_HOVER": "#95E4C5",
}

# Themes built from three colours each: the first is the ground (with a little of the second
# mixed in), the second is the text, the third is kept for buttons, animation and effects.
# Generated and contrast-checked (text >= 4.5:1 on every surface, button text >= 4.5:1).
INDIGO: dict[str, str] = {   # Indigo, celadon & gold (dark)
    "WHITE": "#2B2C58",
    "INK": "#C9ECCB",
    "TEXT": "#ACE1AF",
    "MUTED": "#81A592",
    "SUBTLE": "#688181",
    "BORDER": "#3A4262",
    "BORDER_STRONG": "#49566C",
    "BORDER_HOVER": "#5E747A",
    "FIELD_BG": "#211E51",
    "DISABLED_BG": "#2C2D59",
    "LEAF": "#E6B422",
    "LEAF_DARK": "#F2C94C",
    "OCEAN": "#B8E6BB",
    "OCEAN_DARK": "#BFE8C1",
    "MINT": "#32355C",
    "SKY": "#2E2F59",
    "FOAM": "#2B2C58",
    "PAGE_BG": "#242253",
    "HEADER_GREEN": "#2F315A",
    "HEADER_BLUE": "#34395E",
    "HEADER_LINE": "#3A4262",
    "ERROR": "#FF8F8F",
    "ERROR_BG": "#3E2F5A",
    "SUCCESS": "#8FE3B0",
    "SUCCESS_BG": "#31395E",
    "INFO_BG": "#33365D",
    "ERROR_BORDER": "#7C4E6B",
    "SUCCESS_BORDER": "#4F6F78",
    "INFO_BORDER": "#586777",
    "ERROR_FIELD_BG": "#2E2555",
    "PRIMARY_TEXT": "#1A1640",
    "PRIMARY_DISABLED_TEXT": "#6C8784",
    "PRIMARY_DISABLED_FROM": "#3C4464",
    "PRIMARY_DISABLED_TO": "#3C4464",
    "ACCENT_FROM": "#E6B422",
    "ACCENT_TO": "#E6B422",
    "ACCENT_FROM_HOVER": "#F2C94C",
    "ACCENT_TO_HOVER": "#F2C94C",
    "ACCENT_TEXT": "#1A1640",
    "ACCENT_SOFT": "#3F364C",
    "OPEN_BUTTON_TOP": "#F2C94C",
    "PAGE_GRADIENT_TOP": "#242253",
    "PAGE_GRADIENT_MIDDLE": "#282856",
    "PAGE_GRADIENT_BOTTOM": "#2C2D59",
    "HERO_TOP": "#292A57",
    "HERO_MIDDLE": "#2E2F59",
    "HERO_BOTTOM": "#32355C",
    "TILE_DISABLED_BG": "#282856",
    "PROGRESS_TRACK": "#373D60",
    "PROGRESS_PAUSED": "#7A9B8D",
    "PROGRESS_FAILED": "#C7727F",
    "TABLE_LINE": "#2F325B",
    "CHART_GRID": "#32365C",
    "SHADOW": "#000000",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#E6B422",
    "BUTTON_HOVER": "#F2C94C",
}

NAVY: dict[str, str] = {   # Navy, cream & coral (dark)
    "WHITE": "#24304A",
    "INK": "#F7F1E2",
    "TEXT": "#F3E9D2",
    "MUTED": "#AFACA5",
    "SUBTLE": "#86888A",
    "BORDER": "#3D475B",
    "BORDER_STRONG": "#535B6A",
    "BORDER_HOVER": "#767980",
    "FIELD_BG": "#142240",
    "DISABLED_BG": "#25324C",
    "LEAF": "#FF7F66",
    "LEAF_DARK": "#FF9B87",
    "OCEAN": "#F5ECD9",
    "OCEAN_DARK": "#F6EEDD",
    "MINT": "#2E3A51",
    "SKY": "#27344D",
    "FOAM": "#23304A",
    "PAGE_BG": "#182643",
    "HEADER_GREEN": "#2A364E",
    "HEADER_BLUE": "#323D54",
    "HEADER_LINE": "#3D475B",
    "ERROR": "#FF8FA3",
    "ERROR_BG": "#34334F",
    "SUCCESS": "#9FE0BE",
    "SUCCESS_BG": "#283C52",
    "INFO_BG": "#2E3A52",
    "ERROR_BORDER": "#745069",
    "SUCCESS_BORDER": "#4E7074",
    "INFO_BORDER": "#656B78",
    "ERROR_FIELD_BG": "#222946",
    "PRIMARY_TEXT": "#0F1E3D",
    "PRIMARY_DISABLED_TEXT": "#8C8E8F",
    "PRIMARY_DISABLED_FROM": "#3F495D",
    "PRIMARY_DISABLED_TO": "#3F495D",
    "ACCENT_FROM": "#FF7F66",
    "ACCENT_TO": "#FF7F66",
    "ACCENT_FROM_HOVER": "#FF9B87",
    "ACCENT_TO_HOVER": "#FF9B87",
    "ACCENT_TEXT": "#0F1E3D",
    "ACCENT_SOFT": "#383248",
    "OPEN_BUTTON_TOP": "#FF9B87",
    "PAGE_GRADIENT_TOP": "#182643",
    "PAGE_GRADIENT_MIDDLE": "#1F2C47",
    "PAGE_GRADIENT_BOTTOM": "#25324C",
    "HERO_TOP": "#212E49",
    "HERO_MIDDLE": "#27344D",
    "HERO_BOTTOM": "#2E3A51",
    "TILE_DISABLED_BG": "#1F2C47",
    "PROGRESS_TRACK": "#374157",
    "PROGRESS_PAUSED": "#A3A29E",
    "PROGRESS_FAILED": "#C3738A",
    "TABLE_LINE": "#2A364F",
    "CHART_GRID": "#2F3A52",
    "SHADOW": "#000000",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#FF7F66",
    "BUTTON_HOVER": "#FF9B87",
}

BONE: dict[str, str] = {   # Skeleton cream, black & green (light)
    "WHITE": "#F5F0E3",
    "INK": "#0E0E0E",
    "TEXT": "#111110",
    "MUTED": "#535048",
    "SUBTLE": "#7B766A",
    "BORDER": "#C1B9A6",
    "BORDER_STRONG": "#ABA494",
    "BORDER_HOVER": "#8A8477",
    "FIELD_BG": "#F9F5ED",
    "DISABLED_BG": "#D7CFB9",
    "LEAF": "#28603B",
    "LEAF_DARK": "#255A37",
    "OCEAN": "#10100F",
    "OCEAN_DARK": "#0F0F0F",
    "MINT": "#CFC7B2",
    "SKY": "#D5CDB7",
    "FOAM": "#D9D1BB",
    "PAGE_BG": "#E4DBC4",
    "HEADER_GREEN": "#D3CBB6",
    "HEADER_BLUE": "#CBC3AE",
    "HEADER_LINE": "#C1B9A6",
    "ERROR": "#A3241B",
    "ERROR_BG": "#DCC5B0",
    "SUCCESS": "#1F5E3B",
    "SUCCESS_BG": "#CCCCB4",
    "INFO_BG": "#CFC7B2",
    "ERROR_BORDER": "#CA9280",
    "SUCCESS_BORDER": "#95A98D",
    "INFO_BORDER": "#9A9485",
    "ERROR_FIELD_BG": "#F4E8E0",
    "PRIMARY_TEXT": "#FFFFFF",
    "PRIMARY_DISABLED_TEXT": "#747065",
    "PRIMARY_DISABLED_FROM": "#BEB7A4",
    "PRIMARY_DISABLED_TO": "#BEB7A4",
    "ACCENT_FROM": "#2F6E44",
    "ACCENT_TO": "#2F6E44",
    "ACCENT_FROM_HOVER": "#255A37",
    "ACCENT_TO_HOVER": "#255A37",
    "ACCENT_TEXT": "#FFFFFF",
    "ACCENT_SOFT": "#CBCCB2",
    "OPEN_BUTTON_TOP": "#255A37",
    "PAGE_GRADIENT_TOP": "#E4DBC4",
    "PAGE_GRADIENT_MIDDLE": "#DED5BF",
    "PAGE_GRADIENT_BOTTOM": "#D7CFB9",
    "HERO_TOP": "#DCD3BD",
    "HERO_MIDDLE": "#D5CDB7",
    "HERO_BOTTOM": "#CFC7B2",
    "TILE_DISABLED_BG": "#DED5BF",
    "PROGRESS_TRACK": "#C6BFAB",
    "PROGRESS_PAUSED": "#5E5A52",
    "PROGRESS_FAILED": "#B65447",
    "TABLE_LINE": "#D3CAB5",
    "CHART_GRID": "#CEC6B2",
    "SHADOW": "#0A0A0A",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#2F6E44",
    "BUTTON_HOVER": "#255A37",
}

SEAL: dict[str, str] = {   # Seal blue, navy & crimson (light)
    "WHITE": "#DFE7F0",
    "INK": "#0C1C3D",
    "TEXT": "#0E2148",
    "MUTED": "#3A4C6D",
    "SUBTLE": "#657693",
    "BORDER": "#A0AFC5",
    "BORDER_STRONG": "#8D9EB5",
    "BORDER_HOVER": "#72839E",
    "FIELD_BG": "#EAF0F6",
    "DISABLED_BG": "#B2C2D5",
    "LEAF": "#851637",
    "LEAF_DARK": "#9A1D42",
    "OCEAN": "#0D1F44",
    "OCEAN_DARK": "#0D1E41",
    "MINT": "#ACBBCF",
    "SKY": "#B1C0D4",
    "FOAM": "#B4C3D6",
    "PAGE_BG": "#BDCCDE",
    "HEADER_GREEN": "#AFBED2",
    "HEADER_BLUE": "#A8B7CC",
    "HEADER_LINE": "#A0AFC5",
    "ERROR": "#8A1515",
    "ERROR_BG": "#B7B6C6",
    "SUCCESS": "#174F38",
    "SUCCESS_BG": "#A9BDCA",
    "INFO_BG": "#ABBBCF",
    "ERROR_BORDER": "#A9838E",
    "SUCCESS_BORDER": "#7B9A9C",
    "INFO_BORDER": "#7F8FA8",
    "ERROR_FIELD_BG": "#E4E3E8",
    "PRIMARY_TEXT": "#FFFFFF",
    "PRIMARY_DISABLED_TEXT": "#60718E",
    "PRIMARY_DISABLED_FROM": "#9EADC3",
    "PRIMARY_DISABLED_TO": "#9EADC3",
    "ACCENT_FROM": "#B8244F",
    "ACCENT_TO": "#B8244F",
    "ACCENT_FROM_HOVER": "#9A1D42",
    "ACCENT_TO_HOVER": "#9A1D42",
    "ACCENT_TEXT": "#FFFFFF",
    "ACCENT_SOFT": "#BCB4CA",
    "OPEN_BUTTON_TOP": "#9A1D42",
    "PAGE_GRADIENT_TOP": "#BDCCDE",
    "PAGE_GRADIENT_MIDDLE": "#B8C7DA",
    "PAGE_GRADIENT_BOTTOM": "#B2C2D5",
    "HERO_TOP": "#B6C5D8",
    "HERO_MIDDLE": "#B1C0D4",
    "HERO_BOTTOM": "#ACBBCF",
    "TILE_DISABLED_BG": "#B8C7DA",
    "PROGRESS_TRACK": "#A4B4C9",
    "PROGRESS_PAUSED": "#4E5F7F",
    "PROGRESS_FAILED": "#984449",
    "TABLE_LINE": "#AEBED1",
    "CHART_GRID": "#ABBACE",
    "SHADOW": "#08142B",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#B8244F",
    "BUTTON_HOVER": "#9A1D42",
}

MIDNIGHT: dict[str, str] = {   # Midnight, electric blue & cantaloupe (dark): GEE-Assist-Web's
    # default dark theme (its "midnight", chosen when the OS is in dark mode). Colours from the web's
    # tokens.css; the few keys the web has no token for are filled in from its own colours.
    "WHITE": "#121218",             # --surface
    "INK": "#F3F5FB",               # --ink
    "TEXT": "#D2D7E3",              # --text
    "MUTED": "#9AA0B2",             # --muted
    "SUBTLE": "#6E7488",            # --subtle
    "BORDER": "#23242E",            # --border
    "BORDER_STRONG": "#363846",     # --border-strong
    "BORDER_HOVER": "#4A4D5E",
    "FIELD_BG": "#0C0C12",          # --field
    "DISABLED_BG": "#15151C",
    "LEAF": "#2F80FF",              # --leaf: electric blue (buttons, glows)
    "LEAF_DARK": "#5A9BFF",         # --leaf-dark
    "OCEAN": "#FF9F5A",             # --ocean: cantaloupe (the secondary)
    "OCEAN_DARK": "#FFB77E",        # --ocean-dark
    "MINT": "#122235",              # --mint
    "SKY": "#10203A",               # --sky
    "FOAM": "#14151C",              # --foam
    "PAGE_BG": "#070709",           # --page
    "HEADER_GREEN": "#0F1F36",      # --header-green
    "HEADER_BLUE": "#121019",       # --header-blue
    "HEADER_LINE": "#23242E",
    "ERROR": "#FF8F80",             # --error
    "ERROR_BG": "#331D1D",          # --error-bg
    "SUCCESS": "#46D39A",           # --success
    "SUCCESS_BG": "#0F2E26",        # --success-bg
    "INFO_BG": "#0F1F36",           # --info-bg
    "ERROR_BORDER": "#5C3733",      # --error-border
    "SUCCESS_BORDER": "#225C48",    # --success-border
    "INFO_BORDER": "#27456E",       # --info-border
    "ERROR_FIELD_BG": "#1A0F12",
    "PRIMARY_TEXT": "#06080F",      # --on-primary
    "PRIMARY_DISABLED_TEXT": "#6E7488",
    "PRIMARY_DISABLED_FROM": "#23242E",
    "PRIMARY_DISABLED_TO": "#23242E",
    "ACCENT_FROM": "#2F80FF",       # --fx-a
    "ACCENT_TO": "#2F80FF",
    "ACCENT_FROM_HOVER": "#5A9BFF", # --fx-a-hover
    "ACCENT_TO_HOVER": "#5A9BFF",
    "ACCENT_TEXT": "#06080F",       # --fx-on
    "ACCENT_SOFT": "#122235",       # --fx-soft
    "OPEN_BUTTON_TOP": "#5A9BFF",
    "PAGE_GRADIENT_TOP": "#070709",  # --page
    "PAGE_GRADIENT_MIDDLE": "#0D0D13",  # --page-2
    "PAGE_GRADIENT_BOTTOM": "#121218",
    "HERO_TOP": "#0D0D13",
    "HERO_MIDDLE": "#101017",
    "HERO_BOTTOM": "#14151C",
    "TILE_DISABLED_BG": "#0D0D13",
    "PROGRESS_TRACK": "#23242E",
    "PROGRESS_PAUSED": "#9AA0B2",
    "PROGRESS_FAILED": "#D9786C",
    "TABLE_LINE": "#1C1D26",
    "CHART_GRID": "#1F2029",
    "SHADOW": "#000000",
    "SPLASH_BG": "#FFFFFF",
    "BUTTON": "#2F80FF",
    "BUTTON_HOVER": "#5A9BFF",
}

PALETTES = {
    "light": LIGHT, "dark-green": DARK_GREEN, "dark-grey": DARK_GREY,
    "indigo": INDIGO, "navy": NAVY, "bone": BONE, "seal": SEAL, "midnight": MIDNIGHT,
}
# Themes with light text on a dark ground (the rest are light grounds with dark text).
DARK_THEMES = frozenset({"dark-green", "dark-grey", "indigo", "navy", "midnight"})
# Themes built from three colours: every layout takes its surfaces from them (no fixed console
# colours), and their third colour is kept for buttons, animation and effects.
THREE_COLOUR_THEMES = frozenset({"indigo", "navy", "bone", "seal", "midnight"})

# The theme at start-up is the saved choice (``GEE_ASSIST_THEME`` overrides it, e.g. for the
# tests). Changing it later goes through set_theme() below: it applies at once, with no restart.
_override = os.environ.get("GEE_ASSIST_THEME")
THEME: str = _override if _override in PALETTES else appearance.current_theme()
ACTIVE: dict[str, str] = PALETTES[THEME]
IS_DARK: bool = THEME in DARK_THEMES


def set_theme(name: str) -> None:
    """Swap the active palette in place, for a live theme change (no restart).

    Callers then recompute the dependent colour constants via ``accent.refresh``,
    ``theme.refresh`` and ``form_theme.refresh`` and re-apply the stylesheets.
    """
    global THEME, ACTIVE, IS_DARK
    if name not in PALETTES:
        raise ValueError(f"Unknown theme: {name!r}")
    THEME = name
    ACTIVE = PALETTES[name]
    IS_DARK = name in DARK_THEMES
