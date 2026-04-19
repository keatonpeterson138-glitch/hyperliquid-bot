"""Theme constants – Hyperliquid-style dark trading terminal."""

# ── Colour palette (Hyperliquid aesthetic) ───────────────────────
BG_DARK      = "#0b0e11"   # main background (near black)
BG_CARD      = "#141921"   # card / panel background
BG_INPUT     = "#1e2329"   # input / entry background
BORDER       = "#2b3139"   # subtle borders
TEXT          = "#eaecef"   # primary text
TEXT_DIM      = "#848e9c"  # secondary / muted text
ACCENT        = "#2edba0"  # teal/mint – links, active elements
GREEN         = "#0ecb81"  # profit / long / buy
RED           = "#f6465d"  # loss / short / sell
YELLOW        = "#f0b90b"  # warnings
ORANGE        = "#f0883e"  # caution
WHITE         = "#ffffff"

# Font families
FONT_FAMILY   = "Segoe UI"
FONT_MONO     = "Cascadia Mono"

# Font tuples  (family, size, ?weight)
FONT_TITLE    = (FONT_FAMILY, 18, "bold")
FONT_HEADING  = (FONT_FAMILY, 13, "bold")
FONT_BODY     = (FONT_FAMILY, 11)
FONT_SMALL    = (FONT_FAMILY, 10)
FONT_TINY     = (FONT_FAMILY, 9)
FONT_MONO_SM  = (FONT_MONO, 10)
FONT_MONO_MD  = (FONT_MONO, 12)
FONT_MONO_LG  = (FONT_MONO, 20, "bold")
FONT_MONO_XL  = (FONT_MONO, 28, "bold")

# Padding / sizing helpers
PAD_X = 12
PAD_Y = 8
CARD_PAD = 14
CORNER = 8
