"""
ui_components.py — GENFORGE centralized UI primitives with premium theme system.

All HTML/CSS helpers live here so app.py, studio_pages.py, and
publishing_pages.py reference a single source of truth. Every helper
returns an HTML string that is safe to pass to st.markdown(...,
unsafe_allow_html=True).

No Streamlit widgets are called from this module — it is pure string
generation. This keeps it testable without a running Streamlit session.

THEME SYSTEM:
The design supports both dark and light themes through tokenized CSS variables.
All colors are defined in theme dictionaries and injected as CSS custom properties.
"""

from __future__ import annotations

import html as _html
from typing import Literal

# ===========================================================================
# THEME DEFINITIONS — Dark & Light
# ===========================================================================

THEME_DARK = {
    # Backgrounds
    "bg": "#070A0E",
    "app_bg": "#070A0E",
    "s0": "#05070A",  # deepest canvas
    "s1": "#0E1218",  # default card
    "s2": "#111520",  # elevated panel
    "s3": "#1A2030",  # hover/selected
    "sidebar": "#0A0D12",
    "sidebar_grad": "linear-gradient(180deg, #0A0D12 0%, #0C0F15 100%)",
    "editor_bg": "#03050A",
    "canvas": "#05070A",
    "card": "#0E1218",
    "card_grad": "linear-gradient(145deg, #0B1018 0%, #0F1520 100%)",
    "card_border": "#182030",
    "card_hover": "#223040",
    "panel": "#0E1218",
    "panel_2": "#111520",
    "input_bg": "#0D1118",
    "input_border": "#1E2A38",
    "uploader_bg": "#0D1118",
    "uploader_fg": "#F0F4FF",
    "uploader_muted": "#9AA4B2",
    "uploader_border": "#2E3A50",
    "uploader_hover_bg": "#141A26",
    "uploader_hover_border": "#818CF8",
    "uploader_icon": "#818CF8",
    "uploader_button_bg": "#1A2030",
    "uploader_button_fg": "#F0F4FF",
    "track_bg": "#030508",
    "button_bg": "#131820",
    "button_border": "#1E2A38",
    "button_hover": "#1C2233",
    "button_fg": "#B0B9C8",
    "button_hover_fg": "#F0F4FF",
    "button_active_bg": "#252D40",
    "button_active_fg": "#FFFFFF",
    "button_primary_fg": "#FFFFFF",
    "button_disabled_bg": "#171C24",
    "button_disabled_fg": "#667085",
    "disabled_bg": "#171C24",
    "disabled_fg": "#667085",
    "disabled_border": "#273244",
    "focus_ring": "rgba(129,140,248,0.45)",
    "selected_bg": "rgba(99,102,241,0.14)",
    "hover_bg": "#1A2030",
    "active_bg": "rgba(99,102,241,0.20)",
    "table_header": "#111520",
    "table_row_alt": "#0B1018",
    "overlay": "rgba(5,7,10,0.88)",
    
    # Text
    "fg": "#F0F4FF",
    "muted": "#9AA4B2",
    "faint": "#6B7686",
    "dim": "#4A5568",
    "fg_inv": "#FFFFFF",
    
    # Accent
    "accent": "#818CF8",
    "accent_strong": "#6366F1",
    "accent_2": "#A78BFA",
    "accent_3": "#60A5FA",
    "accent_soft": "rgba(129,140,248,0.12)",
    "accent_med": "rgba(129,140,248,0.20)",
    "accent_line": "rgba(129,140,248,0.45)",
    
    # Borders
    "border": "#1E2A38",
    "border_2": "#2E3A50",
    "border_accent": "rgba(129,140,248,0.35)",
    "hairline": "#14202E",
    
    # Effects
    "shadow": "0 1px 3px rgba(0,0,0,.3)",
    "shadow_md": "0 4px 12px rgba(0,0,0,.4)",
    "shadow_lift": "0 8px 24px rgba(0,0,0,.5)",
    "glow": "0 0 12px rgba(99,102,241,.4)",
    "glow_strong": "0 0 20px rgba(99,102,241,.6)",
    "glass_bg": "rgba(14,18,24,0.7)",
    "glass_border": "rgba(129,140,248,0.15)",
    "glass_blur": "blur(12px)",
    
    # Gradients
    "grad_primary": "linear-gradient(135deg, #4F46E5 0%, #6366F1 50%, #818CF8 100%)",
    "grad_primary_hover": "linear-gradient(135deg, #5B52E8 0%, #6E71F4 50%, #8F99FA 100%)",
    "grad_brand": "linear-gradient(135deg, #E8ECF3 30%, #818CF8 100%)",
    "grad_hero": "linear-gradient(135deg, #E8ECF3 0%, #B4BDCF 100%)",
    "grad_surface": "linear-gradient(145deg, #0B1018 0%, #0F1520 100%)",
    "grad_icon": "linear-gradient(135deg, #1A2035 0%, #202840 100%)",
    
    # Semantic
    "good": "#34D399",
    "good_bg": "rgba(52,211,153,0.08)",
    "good_border": "rgba(52,211,153,0.22)",
    "warn": "#FBBF24",
    "warn_bg": "rgba(251,191,36,0.08)",
    "warn_border": "rgba(251,191,36,0.22)",
    "bad": "#F87171",
    "bad_bg": "rgba(248,113,113,0.08)",
    "bad_border": "rgba(248,113,113,0.22)",
    "info": "#60A5FA",
    "info_bg": "rgba(96,165,250,0.08)",
    "info_border": "rgba(96,165,250,0.22)",
}

THEME_LIGHT = {
    # Backgrounds
    "bg": "#F8FAFC",
    "app_bg": "#F8FAFC",
    "s0": "#FFFFFF",  # deepest canvas
    "s1": "#FFFFFF",  # default card
    "s2": "#F1F5F9",  # elevated panel
    "s3": "#E2E8F0",  # hover/selected
    "sidebar": "#FFFFFF",
    "sidebar_grad": "linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%)",
    "editor_bg": "#FAFBFC",
    "canvas": "#FFFFFF",
    "card": "#FFFFFF",
    "card_grad": "linear-gradient(145deg, #FFFFFF 0%, #F8FAFC 100%)",
    "card_border": "#E2E8F0",
    "card_hover": "#CBD5E1",
    "panel": "#FFFFFF",
    "panel_2": "#F1F5F9",
    "input_bg": "#FFFFFF",
    "input_border": "#CBD5E1",
    "uploader_bg": "#FFFFFF",
    "uploader_fg": "#0F172A",
    "uploader_muted": "#475569",
    "uploader_border": "#94A3B8",
    "uploader_hover_bg": "#F1F5F9",
    "uploader_hover_border": "#4F46E5",
    "uploader_icon": "#4F46E5",
    "uploader_button_bg": "#EEF2FF",
    "uploader_button_fg": "#312E81",
    "track_bg": "#F8FAFC",
    "button_bg": "#FFFFFF",
    "button_border": "#CBD5E1",
    "button_hover": "#F1F5F9",
    "button_fg": "#334155",
    "button_hover_fg": "#0F172A",
    "button_active_bg": "#E2E8F0",
    "button_active_fg": "#0F172A",
    "button_primary_fg": "#FFFFFF",
    "button_disabled_bg": "#F1F5F9",
    "button_disabled_fg": "#64748B",
    "disabled_bg": "#F1F5F9",
    "disabled_fg": "#94A3B8",
    "disabled_border": "#CBD5E1",
    "focus_ring": "rgba(79,70,229,0.35)",
    "selected_bg": "rgba(99,102,241,0.10)",
    "hover_bg": "#E2E8F0",
    "active_bg": "rgba(99,102,241,0.16)",
    "table_header": "#F1F5F9",
    "table_row_alt": "#F8FAFC",
    "overlay": "rgba(15,23,42,0.72)",
    
    # Text
    "fg": "#0F172A",
    "muted": "#475569",
    "faint": "#64748B",
    "dim": "#94A3B8",
    "fg_inv": "#FFFFFF",
    
    # Accent
    "accent": "#6366F1",
    "accent_strong": "#4F46E5",
    "accent_2": "#8B5CF6",
    "accent_3": "#3B82F6",
    "accent_soft": "rgba(99,102,241,0.1)",
    "accent_med": "rgba(99,102,241,0.2)",
    "accent_line": "rgba(99,102,241,0.4)",
    
    # Borders
    "border": "#E2E8F0",
    "border_2": "#CBD5E1",
    "border_accent": "rgba(99,102,241,0.3)",
    "hairline": "#F1F5F9",
    
    # Effects
    "shadow": "0 1px 2px rgba(0,0,0,.05)",
    "shadow_md": "0 4px 6px rgba(0,0,0,.07)",
    "shadow_lift": "0 10px 15px rgba(0,0,0,.1)",
    "glow": "0 0 12px rgba(99,102,241,.3)",
    "glow_strong": "0 0 20px rgba(99,102,241,.4)",
    "glass_bg": "rgba(255,255,255,0.7)",
    "glass_border": "rgba(99,102,241,0.2)",
    "glass_blur": "blur(12px)",
    
    # Gradients
    "grad_primary": "linear-gradient(135deg, #4F46E5 0%, #6366F1 50%, #818CF8 100%)",
    "grad_primary_hover": "linear-gradient(135deg, #5B52E8 0%, #6E71F4 50%, #8F99FA 100%)",
    "grad_brand": "linear-gradient(135deg, #1E293B 30%, #6366F1 100%)",
    "grad_hero": "linear-gradient(135deg, #0F172A 0%, #475569 100%)",
    "grad_surface": "linear-gradient(145deg, #FFFFFF 0%, #F8FAFC 100%)",
    "grad_icon": "linear-gradient(135deg, #E0E7FF 0%, #C7D2FE 100%)",
    
    # Semantic
    "good": "#10B981",
    "good_bg": "rgba(16,185,129,0.1)",
    "good_border": "rgba(16,185,129,0.3)",
    "warn": "#F59E0B",
    "warn_bg": "rgba(245,158,11,0.1)",
    "warn_border": "rgba(245,158,11,0.3)",
    "bad": "#EF4444",
    "bad_bg": "rgba(239,68,68,0.1)",
    "bad_border": "rgba(239,68,68,0.3)",
    "info": "#3B82F6",
    "info_bg": "rgba(59,130,246,0.1)",
    "info_border": "rgba(59,130,246,0.3)",
}


def theme_tokens(theme: Literal["dark", "light"] = "light") -> dict:
  """Return theme tokens for the specified theme.

  Invalid values fail loudly so a typo cannot silently select the wrong
  visual mode.
  """
  if theme not in ("dark", "light"):
    raise ValueError(f"Unsupported theme: {theme!r}")
  return THEME_DARK if theme == "dark" else THEME_LIGHT


# ===========================================================================
# DESIGN CONSTANTS (derived from dark theme for backward compatibility)
# ===========================================================================

# Surfaces
BG            = THEME_DARK["bg"]
SURFACE_0     = THEME_DARK["s0"]
SURFACE_1     = THEME_DARK["s1"]
SURFACE_2     = THEME_DARK["s2"]
SURFACE_3     = THEME_DARK["s3"]
SIDEBAR_BG    = THEME_DARK["sidebar"]

# Text
TEXT_PRIMARY  = THEME_DARK["fg"]
TEXT_SECONDARY= THEME_DARK["muted"]
TEXT_TERTIARY = THEME_DARK["faint"]
TEXT_INVERSE  = THEME_DARK["fg_inv"]

# Accent
ACCENT        = THEME_DARK["accent"]
ACCENT_STRONG = THEME_DARK["accent_strong"]
ACCENT_SOFT   = THEME_DARK["accent_soft"]
ACCENT_MED    = THEME_DARK["accent_med"]
ACCENT_LINE   = THEME_DARK["accent_line"]

# Borders
BORDER        = THEME_DARK["border"]
BORDER_STRONG = THEME_DARK["border_2"]
BORDER_ACCENT = THEME_DARK["border_accent"]

# Semantic
SUCCESS       = THEME_DARK["good"]
SUCCESS_BG    = THEME_DARK["good_bg"]
SUCCESS_BORDER= THEME_DARK["good_border"]
WARNING       = THEME_DARK["warn"]
WARNING_BG    = THEME_DARK["warn_bg"]
WARNING_BORDER= THEME_DARK["warn_border"]
ERROR         = THEME_DARK["bad"]
ERROR_BG      = THEME_DARK["bad_bg"]
ERROR_BORDER  = THEME_DARK["bad_border"]
INFO          = THEME_DARK["info"]
INFO_BG       = THEME_DARK["info_bg"]
INFO_BORDER   = THEME_DARK["info_border"]

# Spacing (rem-based, matching baseFontSize=14px)
SPACE_1 = ".25rem"   # 3.5px
SPACE_2 = ".5rem"    # 7px
SPACE_3 = ".75rem"   # 10.5px
SPACE_4 = "1rem"     # 14px
SPACE_5 = "1.5rem"   # 21px
SPACE_6 = "2rem"     # 28px

# Radius
RADIUS_SM  = "6px"
RADIUS_MD  = "8px"
RADIUS_LG  = "10px"
RADIUS_XL  = "12px"
RADIUS_FULL= "9999px"

# Transition
TRANSITION_FAST    = "0.12s ease"
TRANSITION_DEFAULT = "0.18s ease"
TRANSITION_SLOW    = "0.3s ease"

# Typography scale (rem, base 14px)
TEXT_XS   = ".72rem"   # 10px  — labels, metadata
TEXT_SM   = ".82rem"   # 11.5px — captions, secondary
TEXT_BASE = ".88rem"   # 12.3px — default body
TEXT_MD   = ".98rem"   # 13.7px — card headings
TEXT_LG   = "1.1rem"   # 15.4px — section headings
TEXT_XL   = "1.4rem"   # 19.6px — page titles
TEXT_2XL  = "1.8rem"   # 25.2px — hero title


# ===========================================================================
# CSS GENERATION
# ===========================================================================

def get_design_system_css(theme: Literal["dark", "light"] = "light") -> str:
    """Return the complete CSS for the GENFORGE design system v3.

    Complete visual overhaul: professional media studio aesthetic,
    cinema-grade surfaces, bold typography hierarchy, animated micro-
    interactions, and a layout system that communicates power and precision.
    """
    tokens = theme_tokens(theme)
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* ═══════════════════════════════════════════════════════════════
   GENFORGE DESIGN SYSTEM v3 — Professional AI Media Studio
   Cinema-grade dark surfaces · Bold hierarchy · Studio UX
   ═══════════════════════════════════════════════════════════════ */

/* ── Block container top padding ────────────────────────────
   Ensures the GENFORGE header does not clip under the native
   Streamlit top bar. Small top padding so content starts below
   the native bar without a large gap.
   ─────────────────────────────────────────────────────────── */
div[data-testid="stMainBlockContainer"],
.appview-container .main .block-container {{
  padding-top: 3.5rem !important;
}}

/* ── Native Streamlit sidebar navigation controls ────────────
   Ensure both the collapse button (inside sidebar) and the
   expand button (inside stHeader/stToolbar when sidebar is
   collapsed) are always visible and correctly positioned.
   These use the actual Streamlit 1.62 data-testid values.
   ─────────────────────────────────────────────────────────────── */
/* Sidebar collapse button — visible on hover inside the sidebar */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"] button {{
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
}}
/* Expand button — shown in the top toolbar when sidebar is collapsed */
[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"] button {{
  display: flex !important;
  visibility: visible !important;
  opacity: 1 !important;
}}
/* Project card action strip ─────────────────────────────────
   Buttons are compact: height 28px, small font.
   Open (first button in left pair): accent-tinted.
   Delete (right column button): destructive colour.
   No wrapper divs needed — target via button key attributes.
   ─────────────────────────────────────────────────────────── */
/* Compact height for all project action buttons */
button[data-testid^="btn_open_recent_"],
button[data-testid^="btn_rename_recent_"],
button[data-testid^="btn_delete_recent_"] {{
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: center !important;
  justify-content: center !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  height: 28px !important;
  min-height: 28px !important;
  max-height: 28px !important;
  padding: 2px 10px !important;
  font-size: .8rem !important;
  font-weight: 600 !important;
  line-height: 1 !important;
  gap: 4px !important;
}}
/* Force inner <p> tag inside action buttons onto one horizontal line.
   Streamlit renders button labels as <p> elements which default to
   display:block — this stacks the material icon above the text. */
button[data-testid^="btn_open_recent_"] p,
button[data-testid^="btn_rename_recent_"] p,
button[data-testid^="btn_delete_recent_"] p {{
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 4px !important;
  margin: 0 !important;
  padding: 0 !important;
  white-space: nowrap !important;
  line-height: 1 !important;
}}
/* Open button — accent-tinted */
button[data-testid^="btn_open_recent_"] {{
  background: rgba(99,102,241,.12) !important;
  border-color: rgba(99,102,241,.3) !important;
  color: #818CF8 !important;
}}
button[data-testid^="btn_open_recent_"]:hover {{
  background: rgba(99,102,241,.22) !important;
  border-color: rgba(99,102,241,.55) !important;
}}
/* Rename button — ghost */
button[data-testid^="btn_rename_recent_"] {{
  background: transparent !important;
  border-color: #26303E !important;
  color: #8090A8 !important;
}}
/* Delete button — destructive red */
button[data-testid^="btn_delete_recent_"] {{
  background: rgba(239,68,68,.12) !important;
  border-color: rgba(239,68,68,.4) !important;
  color: #F87171 !important;
}}
button[data-testid^="btn_delete_recent_"]:hover {{
  background: #DC2626 !important;
  border-color: #DC2626 !important;
  color: #FFFFFF !important;
}}
/* Unified project card ─────────────────────────────────────────────────────
   Card info row: icon | name+detail (left) | badge+id (right)
   Action row: Open | Rename | spacer | Delete
   The card info is one HTML block; action buttons follow in Streamlit columns.
   ─────────────────────────────────────────────────────────────────────────── */
.gf-project-card-wrap {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px 20px;
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030;
  border-radius: 10px 10px 0 0;
  border-bottom: none;
  margin-bottom: 0;
  animation: gfFadeUp .22s ease both;
}}
.gf-project-card-wrap:hover {{ border-color: #223040; }}
/* Streamlit wraps the card HTML in stMarkdownContainer.
   Give it explicit bottom margin so the button row cannot
   render flush against or over the card text. */
div[data-testid="stMarkdownContainer"]:has(.gf-project-card-wrap) {{
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
  height: auto !important;
  min-height: fit-content !important;
  overflow: visible !important;
}}
/* The element-container Streamlit wraps around each st.markdown call */
div[data-testid="element-container"]:has(.gf-project-card-wrap) {{
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
  overflow: visible !important;
}}
.gf-pcard-left {{
  display: flex; align-items: center;
  gap: 10px; min-width: 0; flex: 1;
}}
.gf-pcard-icon {{
  width: 32px; height: 32px; flex: none; border-radius: 7px;
  background: linear-gradient(135deg, #141E38 0%, #1C2A50 100%);
  border: 1px solid rgba(99,102,241,.25);
  display: flex; align-items: center; justify-content: center; font-size: .95rem;
}}
.gf-pcard-meta {{ min-width: 0; }}
.gf-pcard-name {{
  font-size: .85rem; font-weight: 600; color: #C8D4E8;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  letter-spacing: -.018em; line-height: 1.3; margin-bottom: 1px;
}}
.gf-pcard-detail {{
  font-size: .67rem; color: #354555; line-height: 1.3;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.gf-pcard-right {{
  flex: none; display: flex; flex-direction: column;
  align-items: flex-end; gap: 2px;
}}
.gf-pcard-id {{
  font-size: .6rem; color: #243040;
  font-variant-numeric: tabular-nums; letter-spacing: .02em;
  margin-top: 2px; line-height: 1.2;
}}

/* Action row — stHorizontalBlock containing btn_open_recent_ buttons ────── */
/* Uses :has() to target precisely. Only style visual appearance —
   do NOT touch height/min-height/align-self on columns or vertical blocks
   as those collapse the card info block above. */
div[data-testid="stHorizontalBlock"]:has(button[data-testid^="btn_open_recent_"]) {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%) !important;
  border: 1px solid #182030 !important;
  border-top: none !important;
  border-radius: 0 0 10px 10px !important;
  padding: 6px 14px 8px !important;
  margin-top: 4px !important;
  margin-bottom: 8px !important;
}}
/* Buttons: compact fixed height — do NOT touch column or stVerticalBlock heights */
div[data-testid="stHorizontalBlock"]:has(button[data-testid^="btn_open_recent_"]) button,
div[data-testid="stHorizontalBlock"]:has(button[data-testid*="recent"]) button {{
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: nowrap !important;
  align-items: center !important;
  justify-content: center !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  width: 100% !important;
  height: 28px !important;
  min-height: 28px !important;
  max-height: 28px !important;
  padding: 2px 10px !important;
  font-size: .8rem !important;
  font-weight: 600 !important;
  line-height: 1 !important;
  gap: 6px !important;
}}
/* All children of action row buttons must not wrap */
div[data-testid="stHorizontalBlock"]:has(button[data-testid^="btn_open_recent_"]) button *,
div[data-testid="stHorizontalBlock"]:has(button[data-testid*="recent"]) button * {{
  white-space: nowrap !important;
  flex-wrap: nowrap !important;
  flex-shrink: 0 !important;
}}
/* Inner <p> in action-row buttons — same fix, scoped to action row */
div[data-testid="stHorizontalBlock"]:has(button[data-testid^="btn_open_recent_"]) button p,
div[data-testid="stHorizontalBlock"]:has(button[data-testid*="recent"]) button p {{
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 4px !important;
  margin: 0 !important;
  padding: 0 !important;
  white-space: nowrap !important;
  line-height: 1 !important;
}}
/* Button colours */
button[data-testid^="btn_open_recent_"] {{
  background: rgba(99,102,241,.12) !important;
  border-color: rgba(99,102,241,.3) !important; color: #818CF8 !important;
}}
button[data-testid^="btn_open_recent_"]:hover {{
  background: rgba(99,102,241,.22) !important; border-color: rgba(99,102,241,.55) !important;
}}
button[data-testid^="btn_rename_recent_"] {{
  background: transparent !important; border-color: #26303E !important; color: #8090A8 !important;
}}
button[data-testid^="btn_delete_recent_"] {{
  background: rgba(239,68,68,.12) !important;
  border-color: rgba(239,68,68,.4) !important; color: #F87171 !important;
}}
button[data-testid^="btn_delete_recent_"]:hover {{
  background: #DC2626 !important; border-color: #DC2626 !important; color: #FFFFFF !important;
}}

:root {{
  /* ── Surfaces — 5-layer depth system ── */
  --gf-bg:       {BG};
  --gf-s0:       {SURFACE_0};
  --gf-s1:       {SURFACE_1};
  --gf-s2:       {SURFACE_2};
  --gf-s3:       {SURFACE_3};
  --gf-sidebar:  {SIDEBAR_BG};
  /* Surface with subtle gradient for premium cards */
  --gf-card-grad: linear-gradient(135deg, #12161D 0%, #151A22 100%);
  --gf-editor-bg: #090B0F;
  /* Aliases kept for backward compat with studio_pages.py */
  --gf-card:     {SURFACE_1};
  --gf-panel:    {SURFACE_1};
  --gf-panel-2:  {SURFACE_2};
  --gf-canvas:   {SURFACE_0};

  /* Text */
  --gf-fg:       {TEXT_PRIMARY};
  --gf-muted:    {TEXT_SECONDARY};
  --gf-faint:    {TEXT_TERTIARY};
  --gf-fg-inv:   {TEXT_INVERSE};

  /* Accent */
  --gf-accent:        {ACCENT};
  --gf-accent-strong: {ACCENT_STRONG};
  --gf-accent-soft:   {ACCENT_SOFT};
  --gf-accent-med:    {ACCENT_MED};
  --gf-accent-line:   {ACCENT_LINE};
  --gf-ring:          {ACCENT_LINE};
  --gf-ring-soft:     {ACCENT_MED};
  /* Aliases */
  --gf-primary:    {ACCENT_STRONG};
  --gf-primary-fg: {TEXT_INVERSE};

  /* Borders */
  --gf-border:        {BORDER};
  --gf-border-2:      {BORDER_STRONG};
  --gf-border-accent: {BORDER_ACCENT};

  /* Semantic */
  --gf-good:          {SUCCESS};
  --gf-good-bg:       {SUCCESS_BG};
  --gf-good-border:   {SUCCESS_BORDER};
  --gf-warn:          {WARNING};
  --gf-warn-bg:       {WARNING_BG};
  --gf-warn-border:   {WARNING_BORDER};
  --gf-bad:           {ERROR};
  --gf-bad-bg:        {ERROR_BG};
  --gf-bad-border:    {ERROR_BORDER};
  --gf-info:          {INFO};
  --gf-info-bg:       {INFO_BG};
  --gf-info-border:   {INFO_BORDER};

  /* Elevation */
  --gf-shadow:      0 1px 2px rgba(0,0,0,.35);
  --gf-shadow-md:   0 4px 12px rgba(0,0,0,.4);
  --gf-shadow-lift: 0 8px 24px rgba(0,0,0,.5);

  /* Spacing */
  --sp-1: {SPACE_1}; --sp-2: {SPACE_2}; --sp-3: {SPACE_3};
  --sp-4: {SPACE_4}; --sp-5: {SPACE_5}; --sp-6: {SPACE_6};

  /* Radius */
  --r-sm:   {RADIUS_SM};
  --r-md:   {RADIUS_MD};
  --r-lg:   {RADIUS_LG};
  --r-xl:   {RADIUS_XL};
  --r-full: {RADIUS_FULL};

  /* Transition */
  --t-fast:    {TRANSITION_FAST};
  --t-default: {TRANSITION_DEFAULT};
  --t-slow:    {TRANSITION_SLOW};

  /* Typography */
  --text-xs:   {TEXT_XS};
  --text-sm:   {TEXT_SM};
  --text-base: {TEXT_BASE};
  --text-md:   {TEXT_MD};
  --text-lg:   {TEXT_LG};
  --text-xl:   {TEXT_XL};
  --text-2xl:  {TEXT_2XL};
}}

/* ── Motion ──────────────────────────────────────────────────── */
@keyframes gfFadeUp {{
  from {{ opacity:0; transform:translateY(6px); }}
  to   {{ opacity:1; transform:none; }}
}}
@keyframes gfFadeIn {{
  from {{ opacity:0; }}
  to   {{ opacity:1; }}
}}
@keyframes gfSlideInLeft {{
  from {{ opacity:0; transform:translateX(-8px); }}
  to   {{ opacity:1; transform:none; }}
}}
@keyframes gfPulse {{
  0%,100% {{ opacity:.6; }}
  50%      {{ opacity:1; }}
}}
@keyframes gfSpin {{
  from {{ transform:rotate(0deg); }}
  to   {{ transform:rotate(360deg); }}
}}
@keyframes gfShimmer {{
  0%   {{ background-position:200% 0; }}
  100% {{ background-position:-200% 0; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation: none !important;
    transition: none !important;
  }}
}}

/* ── App shell ───────────────────────────────────────────────── */
.stApp {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #070A0E;
  color: var(--gf-fg);
}}
h1,h2,h3,h4 {{ letter-spacing:-.025em; color:var(--gf-fg); font-weight:600; }}
.stCaption   {{ color:var(--gf-muted); font-size:var(--text-sm); }}
.stMarkdown  {{ color:var(--gf-fg); }}
.block-container {{
  padding-top: 3.5rem;
  padding-bottom: 2.5rem;
  max-width: 1640px;
}}
.stApp [data-testid="stVerticalBlock"] {{ gap:.55rem; }}
/* ── Sidebar ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #0A0D12 0%, #0C0F15 100%) !important;
  border-right: 1px solid #1E2530 !important;
  box-shadow: 2px 0 20px rgba(0,0,0,.4) !important;
}}
[data-testid="stSidebar"] > div:first-child {{
  padding: 1.1rem .85rem 2rem;
}}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  width: 100%; border-radius: 8px; padding: 7px 11px;
  transition: all .14s ease; position: relative; margin-bottom: 1px;
  border: 1px solid transparent;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  background: rgba(129,140,248,.07);
  border-color: rgba(129,140,248,.12);
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: rgba(99,102,241,.14) !important;
  border-color: rgba(99,102,241,.3) !important;
  box-shadow: 0 0 0 1px rgba(99,102,241,.1) inset;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked)::before {{
  content: ""; position: absolute; left: 0; top: 5px; bottom: 5px;
  width: 3px; background: linear-gradient(180deg, #818CF8, #6366F1);
  border-radius: 0 3px 3px 0; box-shadow: 0 0 8px rgba(129,140,248,.6);
}}
[data-testid="stSidebar"] [role="radiogroup"] label p {{
  font-size: .83rem; font-weight: 500; color: #7A8599; margin: 0; line-height: 1.4;
  letter-spacing: -.005em;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover p {{ color: #C8D0DC; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{
  color: #E2E8F0 !important; font-weight: 600;
}}
/* ── Tabs ────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
  gap: 0; background: #0A0D12;
  border-bottom: 1px solid #1A2232;
  padding: 0 4px; border-radius: 10px 10px 0 0;
  overflow-x: auto; overflow-y: hidden; flex-wrap: nowrap; scrollbar-width: thin;
}}
.stTabs [data-baseweb="tab"] {{
  padding: 9px 14px; color: #5A6474; font-size: .78rem; font-weight: 500;
  background: transparent; transition: all .13s ease;
  white-space: nowrap; flex: none; border-bottom: 2px solid transparent;
  letter-spacing: -.005em;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: #9CA8B8; }}
.stTabs [aria-selected="true"] {{
  color: #C8D4E8 !important; font-weight: 600 !important;
  background: transparent !important;
  border-bottom: 2px solid #6366F1 !important;
  box-shadow: none !important;
  text-shadow: 0 0 20px rgba(129,140,248,.3);
}}
/* ── Buttons ─────────────────────────────────────────────────── */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button {{
  width: 100%; border-radius: 8px; border: 1px solid #1E2A38;
  background: linear-gradient(135deg, #131820 0%, #161C26 100%);
  color: #B0B9C8; font-weight: 500; font-size: .82rem; min-height: 34px;
  padding: 6px 14px; letter-spacing: -.008em;
  transition: all .13s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.03);
  white-space: normal; overflow-wrap: normal; word-break: normal; min-width: 0;
}}
.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {{
  background: linear-gradient(135deg, #181E2A 0%, #1C2233 100%);
  border-color: rgba(129,140,248,.3); color: #E2E8F0;
  box-shadow: 0 2px 8px rgba(0,0,0,.4), 0 0 0 1px rgba(129,140,248,.1);
  transform: translateY(-1px);
}}
.stButton > button:active,
.stDownloadButton > button:active,
.stFormSubmitButton > button:active {{ transform: translateY(0) scale(.98); }}
.stButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primary"] {{
  background: linear-gradient(135deg, #4F46E5 0%, #6366F1 50%, #818CF8 100%) !important;
  color: #FFFFFF !important; border-color: transparent !important;
  font-weight: 600 !important; letter-spacing: -.01em;
  box-shadow: 0 3px 12px rgba(99,102,241,.45), 0 1px 2px rgba(0,0,0,.3),
              inset 0 1px 0 rgba(255,255,255,.15) !important;
  position: relative; overflow: hidden;
}}
.stButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover {{
  box-shadow: 0 4px 18px rgba(99,102,241,.6), 0 2px 4px rgba(0,0,0,.3),
              inset 0 1px 0 rgba(255,255,255,.2) !important;
  filter: brightness(1.08); transform: translateY(-1px);
}}
.stButton > button[kind="primary"]::after {{
  content: ""; position: absolute; inset: 0;
  background: radial-gradient(circle at center, rgba(255,255,255,.25) 0%, transparent 70%);
  opacity: 0; transform: scale(0);
  transition: transform .4s ease-out, opacity .4s ease-out;
}}
.stButton > button[kind="primary"]:active::after {{
  opacity: 1; transform: scale(2.5); transition: none;
}}
.stButton > button:disabled,
.stFormSubmitButton > button:disabled {{ opacity: .35; transform: none; box-shadow: none; }}
.stButton, .stDownloadButton, .stFormSubmitButton {{ min-width: 0; }}
/* ── Inputs ──────────────────────────────────────────────────── */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input {{
  background: #0D1118 !important; border: 1px solid #1E2A38 !important;
  border-radius: 8px !important; color: #E2E8F0 !important;
  font-size: .84rem !important; letter-spacing: -.005em !important;
  box-shadow: inset 0 1px 3px rgba(0,0,0,.4) !important;
  transition: border-color .13s ease, box-shadow .13s ease !important;
}}
.stTextInput input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus {{
  border-color: rgba(99,102,241,.6) !important;
  box-shadow: inset 0 1px 3px rgba(0,0,0,.4), 0 0 0 3px rgba(99,102,241,.18) !important;
}}
[data-baseweb="select"] > div {{
  background: #0D1118 !important; border-color: #1E2A38 !important;
  border-radius: 8px; box-shadow: inset 0 1px 3px rgba(0,0,0,.4);
  min-width: 0; max-width: 100%;
}}
[data-baseweb="select"] span {{ white-space: nowrap; }}
[data-testid="stSelectbox"] {{ min-width: 0; width: 100%; }}
[data-testid="stFileUploader"] {{
  background: linear-gradient(135deg, #0D1118 0%, #111520 100%);
  border: 1px dashed #1E2A38; border-radius: 10px; padding: 6px;
  transition: all .15s ease;
}}
[data-testid="stFileUploader"]:hover {{
  border-color: rgba(99,102,241,.4);
  background: linear-gradient(135deg, #10151F 0%, #141A26 100%);
}}
/* ── Feedback (alerts, metrics, expanders) ────────────────────── */
[data-testid="stAlert"] {{
  border-radius: 10px; border: 1px solid #18202E; font-size: .79rem;
  background: linear-gradient(135deg, #06080D 0%, #090C14 100%);
}}
[data-testid="stMetric"] {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1420 100%);
  border: 1px solid #18202E; border-radius: 10px; padding: 12px 16px;
  box-shadow: 0 2px 10px rgba(0,0,0,.35);
}}
details[data-testid="stExpander"] {{
  border: 1px solid #18202E; border-radius: 10px;
  background: linear-gradient(135deg, #0B1018 0%, #0F1420 100%);
}}
details[data-testid="stExpander"] summary {{
  font-size: .8rem; color: #506070; font-weight: 500;
}}
/* ── Scrollbars ──────────────────────────────────────────────── */
*::-webkit-scrollbar {{ width: 4px; height: 4px; }}
*::-webkit-scrollbar-thumb {{ background: #1A2030; border-radius: 999px; }}
*::-webkit-scrollbar-thumb:hover {{ background: #243040; }}
*::-webkit-scrollbar-track {{ background: transparent; }}
/* ── Focus accessibility ─────────────────────────────────────── */
:focus-visible {{ outline: 2px solid rgba(99,102,241,.85); outline-offset: 2px; }}
.stButton > button:focus-visible,
.stFormSubmitButton > button:focus-visible {{
  outline: 2px solid #6366F1; outline-offset: 2px;
  box-shadow: 0 0 0 4px rgba(99,102,241,.22);
}}
/* ── Card component ──────────────────────────────────────────── */
.gf-card {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030; border-radius: 12px;
  padding: 16px 18px; margin-bottom: 12px;
  box-shadow: 0 2px 14px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.022);
  animation: gfFadeUp .25s ease both;
  transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease;
}}
.gf-card:hover {{
  border-color: #223040;
  box-shadow: 0 4px 24px rgba(0,0,0,.52), inset 0 1px 0 rgba(255,255,255,.03);
  transform: translateY(-1px);
}}
.gf-card-title {{
  font-size: .94rem; font-weight: 600; color: #D0DCEC; margin: 0 0 3px;
  letter-spacing: -.02em;
}}
.gf-card-sub {{ font-size: .73rem; color: #354555; margin: 0; }}
/* Legacy alias */
.studio-card {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030; border-radius: 12px;
  padding: 14px 16px; margin-bottom: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.02);
  animation: gfFadeUp .25s ease both;
  transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease;
}}
.studio-card:hover {{
  border-color: #223040;
  box-shadow: 0 4px 22px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.026);
  transform: translateY(-1px);
}}
.studio-card h3 {{
  font-size: .94rem; font-weight: 600; margin: 0; color: #D0DCEC; letter-spacing: -.02em;
}}
.studio-card p {{ color: #354555; margin-top: 6px; font-size: .78rem; line-height: 1.5; }}
/* ── Project card (Home page) ────────────────────────────────── */
.gf-project-card {{
  display: grid; grid-template-columns: 46px 1fr auto;
  align-items: start; gap: 14px; padding: 14px 16px; margin-bottom: 8px;
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030; border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.02);
  animation: gfFadeUp .25s ease both; transition: all .14s ease; cursor: default;
}}
.gf-project-card:hover {{
  border-color: rgba(99,102,241,.3);
  box-shadow: 0 5px 24px rgba(0,0,0,.5), 0 0 0 1px rgba(99,102,241,.08);
  transform: translateY(-2px);
}}
.gf-project-icon {{
  width: 46px; height: 46px; border-radius: 10px; flex: none;
  background: linear-gradient(135deg, #141E38 0%, #1C2A50 100%);
  border: 1px solid rgba(99,102,241,.28);
  display: flex; align-items: center; justify-content: center; font-size: 1.3rem;
  box-shadow: 0 2px 8px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.04);
}}
.gf-project-meta {{ min-width: 0; padding-top: 2px; }}
.gf-project-name {{
  font-size: .87rem; font-weight: 600; color: #C8D4E8;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  letter-spacing: -.018em; margin-bottom: 4px;
}}
.gf-project-detail {{ font-size: .7rem; color: #354555; overflow-wrap: anywhere; line-height: 1.4; }}
.gf-project-badge {{
  flex: none; display: flex; flex-direction: column;
  align-items: flex-end; gap: 5px; padding-top: 2px;
}}
/* ── Row card (renders list etc.) ────────────────────────────── */
.gf-row-card {{
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 14px; margin-bottom: 6px;
  background: linear-gradient(135deg, #080C14 0%, #0B1020 100%);
  border: 1px solid #162030; border-radius: 10px;
  transition: all .13s ease;
}}
.gf-row-card:hover {{
  border-color: #223040; transform: translateX(2px);
  background: linear-gradient(135deg, #0B1018 0%, #0E1525 100%);
}}
.gf-row-title {{
  font-size: .83rem; font-weight: 600; color: #B8C8D8;
  overflow-wrap: anywhere; letter-spacing: -.012em;
}}
.gf-row-sub {{ font-size: .69rem; color: #354555; margin-top: 2px; overflow-wrap: anywhere; }}
.gf-row-side {{ display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }}
/* ── Status badge (unified — replaces 3 old systems) ─────────── */
.gf-badge {{
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 999px;
  font-size: .63rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; border: 1px solid; white-space: nowrap;
}}
.gf-badge::before {{
  content: ""; width: 4px; height: 4px; border-radius: 50%;
  background: currentColor; flex: none;
}}
.gf-badge-ok   {{ color:#34D399; border-color:rgba(52,211,153,.3);  background:rgba(52,211,153,.07); }}
.gf-badge-warn {{ color:#FBBF24; border-color:rgba(251,191,36,.3);  background:rgba(251,191,36,.07); }}
.gf-badge-err  {{ color:#F87171; border-color:rgba(248,113,113,.3); background:rgba(248,113,113,.07); }}
.gf-badge-info {{ color:#60A5FA; border-color:rgba(96,165,250,.3);  background:rgba(96,165,250,.07); }}
.gf-badge-draft{{ color:#405060; border-color:#16202E; background:transparent; }}
.gf-status-tag {{
  display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:999px;
  font-size:.63rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  border:1px solid #16202E; color:#405060; white-space:nowrap;
}}
.gf-status-tag.ok  {{ color:#34D399; border-color:rgba(52,211,153,.3);  background:rgba(52,211,153,.07); }}
.gf-status-tag.err {{ color:#F87171; border-color:rgba(248,113,113,.3); background:rgba(248,113,113,.07); }}
/* ── System status pills (sidebar) ───────────────────────────── */
.gf-sys-pill, .status-pill-green, .status-pill-red {{
  display: flex; align-items: center; gap: 7px; padding: 5px 10px;
  border-radius: 8px; font-size: .71rem; font-weight: 600;
  margin-bottom: 5px; border: 1px solid transparent; letter-spacing: .01em;
}}
.gf-sys-pill::before, .status-pill-green::before, .status-pill-red::before {{
  content: ""; width: 6px; height: 6px; border-radius: 50%; flex: none;
}}
.gf-sys-pill-on, .status-pill-green {{
  color: #34D399; border-color: rgba(52,211,153,.18); background: rgba(52,211,153,.06);
}}
.gf-sys-pill-on::before, .status-pill-green::before {{
  background: #34D399; box-shadow: 0 0 7px rgba(52,211,153,.75);
}}
.gf-sys-pill-off, .status-pill-red {{
  color: #F87171; border-color: rgba(248,113,113,.18); background: rgba(248,113,113,.06);
}}
.gf-sys-pill-off::before, .status-pill-red::before {{ background: #F87171; }}
/* ── Header status chips ─────────────────────────────────────── */
.gf-status-chip {{
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 999px;
  font-size: .68rem; font-weight: 700; border: 1px solid #1E2A38;
  color: #4A5568; white-space: nowrap; letter-spacing: .03em;
}}
.gf-status-chip::before {{
  content: ""; width: 5px; height: 5px; border-radius: 50%;
  background: currentColor; flex: none; opacity: .8;
}}
.gf-status-chip.chip-on  {{
  color:#34D399; border-color:rgba(52,211,153,.25); background:rgba(52,211,153,.07);
}}
.gf-status-chip.chip-off {{
  color:#F87171; border-color:rgba(248,113,113,.25); background:rgba(248,113,113,.07);
}}
.gf-status-chip.chip-warn {{
  color:#FBBF24; border-color:rgba(251,191,36,.25); background:rgba(251,191,36,.07);
  animation: gfPulse 2s ease-in-out infinite;
}}
/* ── Top bar ─────────────────────────────────────────────────── */
.gf-topbar, .gf-app-header {{
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 10px 18px;
  margin-top: 0 !important;
  background: linear-gradient(135deg, #0E1218 0%, #111520 100%);
  border: 1px solid #1E2A38; border-radius: 12px; margin-bottom: 16px;
  box-shadow: 0 2px 16px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.03);
  animation: gfFadeIn .2s ease both;
}}
.gf-topbar-left {{ display:flex; flex-direction:column; gap:1px; flex:none; }}
.gf-topbar-center, .gf-header-center {{
  flex:1; min-width:0; padding:0 12px; display:flex; flex-direction:column; gap:1px;
}}
.gf-topbar-right, .gf-header-status {{
  display:flex; align-items:center; gap:6px; flex:none;
}}
.gf-page-title {{
  font-size: .88rem; font-weight: 600; color: #C0CCDC; line-height: 1.2;
  letter-spacing: -.015em;
}}
.gf-page-sub, .gf-page-note {{
  font-size: .7rem; color: #3D4A57; overflow-wrap: anywhere; line-height: 1.4;
}}
.gf-project-tag {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: .76rem; font-weight: 600; color: #6B7786; letter-spacing: -.005em;
}}
/* ── Section label ───────────────────────────────────────────── */
.gf-section-label {{
  font-size: .61rem; letter-spacing: .16em; text-transform: uppercase;
  color: #263040; font-weight: 700; margin: 18px 0 7px; display: block;
}}
/* ── Hero (Home page) ────────────────────────────────────────── */
.gf-hero {{ margin-bottom: 24px; animation: gfFadeUp .3s ease both; position: relative; }}
.gf-hero-title, .hero-title {{
  font-size: 2rem; font-weight: 800; letter-spacing: -.04em;
  margin: 0 0 6px; line-height: 1.1; text-wrap: balance;
  background: linear-gradient(135deg, #E8ECF3 0%, #B4BDCF 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; animation: gfFadeUp .28s ease both;
}}
.gf-hero-sub, .hero-sub {{
  font-size: .9rem; color: #4A5568; margin: 0 0 20px; line-height: 1.55;
  animation: gfFadeUp .3s ease .05s both;
}}
/* ── Preview canvas ──────────────────────────────────────────── */
.gf-canvas {{
  background: #03050A; border: 1px solid #182030; border-radius: 12px; padding: 12px;
  box-shadow: inset 0 2px 16px rgba(0,0,0,.65);
}}
.gf-canvas video, .gf-canvas img {{ max-width: 100%; border-radius: 8px; }}
.gf-canvas-empty {{
  background: linear-gradient(135deg, #04060C 0%, #060A14 100%);
  border: 1px dashed #182030; border-radius: 12px; min-height: 280px;
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px; padding: 28px;
  animation: gfFadeIn .35s ease both; text-align: center;
}}
.gf-canvas-empty-icon {{ font-size: 2.2rem; opacity: .15; margin-bottom: 4px; }}
.gf-canvas-empty-title {{ font-size: .88rem; font-weight: 600; color: #263040; letter-spacing: -.015em; }}
.gf-canvas-empty-hint {{ font-size: .76rem; color: #1E2A38; max-width: 300px; line-height: 1.6; }}
/* ── Timeline ────────────────────────────────────────────────── */
.gf-timeline-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }}
.gf-timeline-label {{
  font-size: .61rem; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; color: #263040;
}}
/* Legacy ruler (fallback) */
.gf-timeline-ruler {{
  display: flex; justify-content: space-between; align-items: center;
  color: #263040; font-size: .63rem; letter-spacing: .1em; text-transform: uppercase;
  font-weight: 600; margin: 0 0 6px; padding: 0 4px;
}}
/* Phase 4: proportional time ruler */
.gf-ruler-wrap {{
  position: relative; height: 22px; background: #030508;
  border: 1px solid #14202E; border-radius: 6px; margin: 0 0 4px;
  overflow: hidden;
}}
.gf-ruler-tick {{
  position: absolute; top: 0; bottom: 0;
  border-left: 1px solid #182030;
  display: flex; align-items: flex-end; padding: 0 2px 2px;
}}
.gf-ruler-tick span {{
  font-size: .56rem; font-weight: 600; color: #263040;
  letter-spacing: .04em; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}}
.gf-ruler-playhead {{
  position: absolute; top: 0; bottom: 0;
  width: 12px; transform: translateX(-6px);
  color: #6366F1; font-size: .65rem;
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 1px; z-index: 4; pointer-events: none;
}}
.gf-ruler-total {{
  position: absolute; right: 4px; bottom: 2px;
  font-size: .56rem; font-weight: 600; color: #203040;
  font-variant-numeric: tabular-nums;
}}
/* Phase 4: timeline track wrapper (for playhead overlay) */
.gf-timeline-track-wrap {{
  position: relative; margin: 0 0 10px;
}}
.gf-timeline-track {{
  display: flex; gap: 6px; align-items: stretch;
  min-height: 100px; padding: 10px 14px;
  border: 1px solid #16202E; border-radius: 12px;
  background: linear-gradient(135deg, #030508 0%, #04060C 100%);
  overflow-x: auto; scroll-behavior: smooth;
  box-shadow: inset 0 2px 16px rgba(0,0,0,.55);
  position: relative;
}}
.gf-timeline-track::before {{
  content: ""; position: absolute; left: 14px; right: 14px; top: 50%;
  height: 1px;
  background: linear-gradient(90deg, transparent, #16223A 30%, #16223A 70%, transparent);
  pointer-events: none; z-index: 0;
}}
.gf-timeline-track:empty::after {{
  content: "Add clips to build your editorial sequence";
  color: #1E2A38; font-size: .78rem; align-self: center; margin: auto; z-index: 1;
}}
/* Phase 4: playhead needle over track */
.gf-tl-playhead {{
  position: absolute; top: 0; bottom: 0; width: 2px;
  background: rgba(99,102,241,.85);
  box-shadow: 0 0 6px rgba(99,102,241,.6);
  transform: translateX(-1px);
  pointer-events: none; z-index: 10;
}}
.gf-tl-playhead-head {{
  width: 8px; height: 8px; background: #6366F1;
  border-radius: 50%; position: absolute; top: -4px;
  left: -3px; box-shadow: 0 0 6px rgba(99,102,241,.8);
}}
/* Phase 4: thumbnail strip inside clip block */
.gf-tl-thumb {{
  position: absolute; top: 0; left: 0; right: 0; height: 28px;
  background-size: cover; background-position: center;
  opacity: .18; border-radius: 7px 7px 0 0;
  pointer-events: none;
}}
/* Phase 4: transition marker */
.gf-tl-transition {{
  display: flex; align-items: center; justify-content: center;
  width: 18px; flex: none; color: #6366F1; font-size: .85rem;
  opacity: .7; z-index: 2; align-self: center;
}}
/* Phase 4: audio waveform stub bar */
.gf-tl-audio-bar {{
  height: 4px; margin-top: 4px; border-radius: 2px;
  background: linear-gradient(90deg, #1E3050 0%, #263A5A 20%, #1A2A44 40%,
    #263A5A 60%, #1E3050 80%, #1A2A44 100%);
  background-size: 200% 100%;
  animation: gfShimmer 2.5s linear infinite;
  opacity: .6;
}}
/* Phase 4: timeline badges */
.gf-tl-badge {{
  display: inline-flex; align-items: center;
  font-size: .63rem; font-weight: 700; color: #2A3A4A;
  background: #06080E; border: 1px solid #14202C;
  padding: 1px 7px; border-radius: 6px; letter-spacing: .04em;
  font-variant-numeric: tabular-nums;
}}
.gf-tl-badge-dur {{ color: #344858; }}
.gf-timeline-block {{
  min-width: calc(148px * var(--gf-zoom, 1)); max-width: calc(228px * var(--gf-zoom, 1));
  flex: 1; z-index: 1;
  padding: 9px 11px; border-radius: 8px;
  background: linear-gradient(145deg, #0D1520 0%, #111C2C 100%);
  border: 1px solid #1C2C3E; border-left: 3px solid #223448;
  color: #B0C0D0; font-size: .77rem;
  transition: all .13s ease; cursor: default; user-select: none;
  box-shadow: 0 1px 6px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.02);
  position: relative; overflow: hidden;
}}
.gf-timeline-block::after {{
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.04), transparent);
}}
.gf-timeline-block:hover {{
  background: linear-gradient(145deg, #111C2E 0%, #162438 100%);
  border-color: #283A52; transform: translateY(-2px);
  box-shadow: 0 4px 14px rgba(0,0,0,.48), inset 0 1px 0 rgba(255,255,255,.03);
}}
.gf-timeline-block.selected {{
  background: linear-gradient(145deg, #131830 0%, #182040 100%) !important;
  border-color: rgba(99,102,241,.55) !important;
  border-left-color: #6366F1 !important;
  box-shadow: 0 0 0 1px rgba(99,102,241,.15), 0 4px 18px rgba(99,102,241,.22),
              inset 0 1px 0 rgba(129,140,248,.07) !important;
}}
.gf-timeline-block strong {{
  display: block; color: #28384A; font-size: .6rem; letter-spacing: .1em;
  text-transform: uppercase; font-weight: 700; margin-bottom: 4px;
}}
.gf-timeline-block.selected strong {{ color: #7888F0; }}
.gf-timeline-block span {{
  display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  margin: 3px 0 4px; font-weight: 600; color: #B8C8D8;
  font-size: .79rem; letter-spacing: -.012em;
}}
.gf-timeline-block small {{
  display: block; color: #28384A; font-size: .66rem;
}}
/* Phase 4: Inspector card */
.gf-inspector {{
  background: #050810; border: 1px solid #161E2C; border-radius: 10px;
  padding: 12px 14px; margin-top: 8px;
}}
.gf-inspector-header {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px;
}}
.gf-inspector-title {{
  font-size: .62rem; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; color: #1C2C3C;
}}
.gf-inspector-clip {{
  font-size: .7rem; color: #354555; font-weight: 600;
  background: #0A1218; border: 1px solid #182030;
  padding: 2px 8px; border-radius: 5px;
  max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.gf-inspector-grid {{
  display: grid; grid-template-columns: max-content 1fr; gap: 2px 10px;
  margin-bottom: 10px;
}}
.gf-inspector-key {{
  font-size: .65rem; font-weight: 600; color: #1C2C3C;
  text-transform: uppercase; letter-spacing: .08em;
  white-space: nowrap; align-self: center;
}}
.gf-inspector-val {{
  font-size: .7rem; color: #506070; font-weight: 500;
  font-variant-numeric: tabular-nums;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.gf-inspector-dur-ok {{
  font-size: .7rem; color: #34D399; font-weight: 600; margin-top: 4px;
  font-variant-numeric: tabular-nums;
}}
.gf-inspector-dur-warn {{
  font-size: .7rem; color: #FBBF24; font-weight: 600; margin-top: 4px;
  font-variant-numeric: tabular-nums;
}}
/* ── Metric tiles ────────────────────────────────────────────── */
.gf-metric {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030; border-radius: 10px; padding: 12px 16px;
  animation: gfFadeUp .3s ease both; box-shadow: 0 2px 10px rgba(0,0,0,.32);
}}
.gf-metric-label {{
  font-size: .63rem; text-transform: uppercase; letter-spacing: .1em;
  color: #263040; font-weight: 700;
}}
.gf-metric-value {{
  font-size: 1.1rem; font-weight: 700; margin-top: 4px;
  color: #C0CCE0; letter-spacing: -.025em;
}}
/* ── Empty state ─────────────────────────────────────────────── */
.gf-empty {{
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; padding: 50px 28px; text-align: center;
  animation: gfFadeIn .35s ease both;
}}
.gf-empty-icon {{ font-size: 2.4rem; opacity: .14; }}
.gf-empty-title {{ font-size: .9rem; font-weight: 600; color: #263040; letter-spacing: -.018em; }}
.gf-empty-body {{ font-size: .78rem; color: #1E2A38; max-width: 295px; line-height: 1.65; }}
/* ── Render progress ─────────────────────────────────────────── */
.gf-stage-bar {{ display:flex; gap:4px; align-items:center; margin:10px 0; flex-wrap:wrap; }}
.gf-stage-step {{
  display:flex; align-items:center; gap:5px; padding:4px 11px; border-radius:999px;
  font-size:.65rem; font-weight:700; letter-spacing:.05em;
  background:#07090E; border:1px solid #16202E; color:#263040;
}}
.gf-stage-step.active {{
  background:rgba(99,102,241,.1); border-color:rgba(99,102,241,.38); color:#7888F0;
  animation: gfPulse 1.8s ease-in-out infinite;
}}
.gf-stage-step.done  {{ background:rgba(52,211,153,.07); border-color:rgba(52,211,153,.25); color:#34D399; }}
.gf-stage-step.error {{ background:rgba(248,113,113,.07); border-color:rgba(248,113,113,.25); color:#F87171; }}
/* ── AI status / plan panel ──────────────────────────────────── */
.gf-ai-panel {{
  background: linear-gradient(135deg, #06081A 0%, #080B1E 100%);
  border: 1px solid rgba(99,102,241,.22); border-radius: 12px; padding: 14px 16px;
  animation: gfFadeUp .22s ease both;
  box-shadow: 0 0 26px rgba(99,102,241,.06), inset 0 1px 0 rgba(129,140,248,.04);
}}
.gf-ai-panel-header {{ display:flex; align-items:center; gap:9px; margin-bottom:12px; }}
.gf-ai-dot {{
  width: 8px; height: 8px; border-radius: 50%; background: #6366F1; flex: none;
  animation: gfPulse 1.8s ease-in-out infinite;
  box-shadow: 0 0 10px rgba(99,102,241,.85);
}}
.gf-ai-title {{ font-size:.79rem; font-weight:600; color:#7888F0; letter-spacing:-.012em; }}
.gf-ai-plan-item {{
  display:flex; align-items:flex-start; gap:9px; padding:6px 0;
  border-bottom:1px solid #10182A; font-size:.78rem; color:#8090A8;
}}
.gf-ai-plan-item:last-child {{ border-bottom:none; }}
.gf-ai-plan-check {{ color:#34D399; flex:none; margin-top:1px; font-weight:700; }}
/* ── Notification banner ─────────────────────────────────────── */
.gf-banner {{
  display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:10px;
  font-size:.78rem; margin-bottom:12px; font-weight:500;
  animation:gfSlideInLeft .2s ease both;
}}
.gf-banner-ok   {{ background:rgba(52,211,153,.06);  border:1px solid rgba(52,211,153,.2);  color:#34D399; }}
.gf-banner-warn {{ background:rgba(251,191,36,.06);  border:1px solid rgba(251,191,36,.2);  color:#FBBF24; }}
.gf-banner-err  {{ background:rgba(248,113,113,.06); border:1px solid rgba(248,113,113,.2); color:#F87171; }}
.gf-banner-info {{ background:rgba(96,165,250,.06);  border:1px solid rgba(96,165,250,.2);  color:#60A5FA; }}
/* ── Misc Streamlit overrides ────────────────────────────────── */
.stApp [data-testid="stVerticalBlock"] {{ gap:.55rem; }}
[data-testid="stCheckbox"] label, [data-testid="stSidebar"] [role="radiogroup"] label {{
  word-break:normal; overflow-wrap:normal;
}}
[data-baseweb="select"] span {{ white-space:nowrap; }}
[data-testid="stSelectbox"] {{ min-width:0; width:100%; }}
[data-baseweb="select"]>div {{ min-width:0; max-width:100%; }}
.stTabs [data-baseweb="tab"] {{ white-space:nowrap; flex:none; }}
.stTabs [data-baseweb="tab-list"] {{ overflow-x:auto; overflow-y:hidden; flex-wrap:nowrap; scrollbar-width:thin; }}
.stButton,.stDownloadButton,.stFormSubmitButton {{ min-width:0; }}
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button {{ white-space:normal; overflow-wrap:normal; word-break:normal; }}

/* ── Monospace font for technical content ────────────────────── */
code, .gf-mono, .gf-project-id, .gf-clip-num {{
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace !important;
  font-size: .8rem;
  letter-spacing: -.01em;
}}

/* ── Brand styling improvements ──────────────────────────────── */
.gf-brand {{
  font-family: 'Inter', sans-serif;
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: -.035em;
  color: #F0F4FF;
  line-height: 1;
  background: linear-gradient(135deg, #E8ECF3 30%, #818CF8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.gf-brand-glyph {{
  -webkit-text-fill-color: #6366F1;
  color: #6366F1;
  filter: drop-shadow(0 0 6px rgba(99,102,241,.7));
}}
.gf-kicker {{
  font-size: .65rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: #4A5568;
  font-weight: 600;
}}
@media (max-width:1100px) {{
  [data-testid="stHorizontalBlock"] {{ flex-direction:column!important; gap:10px; }}
  [data-testid="stHorizontalBlock"]>[data-testid="stColumn"] {{
    width:100%!important; flex-basis:auto!important; flex-grow:1!important; max-width:100%!important;
  }}
}}
@media (max-width:900px) {{
  .block-container {{ padding-left:.85rem; padding-right:.85rem; }}
  .gf-app-header, .gf-topbar {{ flex-wrap:wrap; row-gap:8px; }}
  .gf-header-status, .gf-topbar-right {{ margin-left:auto; }}
  .stButton > button {{ width:100%; }}
}}
@media (max-width:760px) {{
  .gf-page-note, .gf-page-sub {{ display:none; }}
}}
/* ── Checkbox/radio label word-break ─────────────────────────── */
[data-testid="stCheckbox"] label,
[data-testid="stSidebar"] [role="radiogroup"] label {{
  word-break: normal;
  overflow-wrap: normal;
}}
/* ── Extra global overrides ─────────────────────────────────── */
.gf-skeleton {{
  background: linear-gradient(90deg, #0B1018 0%, #131D28 40%, #0B1018 80%);
  background-size: 200% 100%; animation: gfShimmer 1.6s infinite; border-radius: 8px;
}}
/* Brand gradient text */
.gf-brand {{
  background: linear-gradient(135deg, #DDE6F8 0%, #9AAAC8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; font-weight: 800; letter-spacing: -.03em;
}}
.gf-brand-glyph {{
  -webkit-text-fill-color: #6366F1; color: #6366F1;
  filter: drop-shadow(0 0 7px rgba(99,102,241,.85));
}}
/* Hero gradient text */
.gf-hero-title, .hero-title {{
  background: linear-gradient(135deg, #D4E0F4 0%, #8898B8 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.stButton, .stDownloadButton, .stFormSubmitButton {{ min-width: 0; }}
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {{
  white-space: normal; overflow-wrap: normal; word-break: normal;
}}
[data-baseweb="select"]>div {{ min-width: 0; max-width: 100%; }}
[data-baseweb="select"] span {{ white-space: nowrap; }}
[data-testid="stSelectbox"] {{ min-width: 0; width: 100%; }}
.stTabs [data-baseweb="tab"] {{ white-space: nowrap; flex: none; }}
.stTabs [data-baseweb="tab-list"] {{
  overflow-x: auto; overflow-y: hidden; flex-wrap: nowrap; scrollbar-width: thin;
}}
/* Video Studio editor layout — preview dominant */
.gf-editor-layout {{
  display: grid;
  grid-template-columns: minmax(0,1fr) 320px;
  gap: 14px;
  align-items: start;
}}
/* Render stage bar connector dots */
.gf-stage-bar > span {{ font-size: .65rem; color: #1A2A3A; }}
/* Clip position badge in timeline */
.gf-clip-pos {{
  display: inline-block; width: 20px; height: 20px; border-radius: 4px;
  background: rgba(99,102,241,.15); border: 1px solid rgba(99,102,241,.3);
  color: #7888F0; font-size: .6rem; font-weight: 700; text-align: center;
  line-height: 20px; flex: none; margin-right: 4px;
}}
/* Status bar at very bottom of editor */
.gf-status-bar {{
  display: flex; align-items: center; gap: 12px;
  padding: 6px 14px; margin-top: 8px;
  background: #04060C; border: 1px solid #14202E; border-radius: 8px;
  font-size: .65rem; color: #283848; letter-spacing: .04em;
}}
.gf-status-bar-item {{ display: flex; align-items: center; gap: 5px; }}
.gf-status-bar-dot {{ width: 4px; height: 4px; border-radius: 50%; background: currentColor; }}
/* Monospace font for technical values */
.gf-mono {{ font-family: 'JetBrains Mono','Cascadia Code','Fira Code',monospace; font-size: .8em; }}
/* Section divider */
.gf-divider {{
  height: 1px; background: linear-gradient(90deg,transparent,#18283A 30%,#18283A 70%,transparent);
  margin: 14px 0; border: none;
}}
/* Gradient accent line on top of cards */
.gf-card-accent {{
  background: linear-gradient(145deg, #0B1018 0%, #0F1520 100%);
  border: 1px solid #182030; border-radius: 12px;
  padding: 16px 18px; margin-bottom: 12px;
  box-shadow: 0 2px 14px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.022);
  animation: gfFadeUp .25s ease both;
  position: relative; overflow: hidden;
}}
.gf-card-accent::before {{
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, #4338CA, #6366F1, #818CF8, #6366F1, #4338CA);
  background-size: 200% 100%;
  animation: gfShimmer 3s linear infinite;
}}

/* ── Selected-theme overrides ─────────────────────────────────────────────
   Legacy component rules above remain for backwards-compatible markup. This
   final layer makes the active token set authoritative for both modes. */
:root {{
  --gf-app-bg: {tokens["app_bg"]};
  --gf-bg: {tokens["bg"]};
  --gf-s0: {tokens["s0"]};
  --gf-s1: {tokens["s1"]};
  --gf-s2: {tokens["s2"]};
  --gf-s3: {tokens["s3"]};
  --gf-sidebar: {tokens["sidebar"]};
  --gf-editor-bg: {tokens["editor_bg"]};
  --gf-canvas: {tokens["canvas"]};
  --gf-card: {tokens["card"]};
  --gf-card-grad: {tokens["card_grad"]};
  --gf-panel: {tokens["panel"]};
  --gf-panel-2: {tokens["panel_2"]};
  --gf-track-bg: {tokens["track_bg"]};
  --gf-input-bg: {tokens["input_bg"]};
  --gf-input-border: {tokens["input_border"]};
  --gf-uploader-bg: {tokens["uploader_bg"]};
  --gf-uploader-fg: {tokens["uploader_fg"]};
  --gf-uploader-muted: {tokens["uploader_muted"]};
  --gf-uploader-border: {tokens["uploader_border"]};
  --gf-uploader-hover-bg: {tokens["uploader_hover_bg"]};
  --gf-uploader-hover-border: {tokens["uploader_hover_border"]};
  --gf-uploader-icon: {tokens["uploader_icon"]};
  --gf-uploader-button-bg: {tokens["uploader_button_bg"]};
  --gf-uploader-button-fg: {tokens["uploader_button_fg"]};
  --gf-fg: {tokens["fg"]};
  --gf-muted: {tokens["muted"]};
  --gf-faint: {tokens["faint"]};
  --gf-dim: {tokens["dim"]};
  --gf-fg-inv: {tokens["fg_inv"]};
  --gf-border: {tokens["border"]};
  --gf-border-2: {tokens["border_2"]};
  --gf-border-accent: {tokens["border_accent"]};
  --gf-hairline: {tokens["hairline"]};
  --gf-accent: {tokens["accent"]};
  --gf-accent-strong: {tokens["accent_strong"]};
  --gf-accent-soft: {tokens["accent_soft"]};
  --gf-accent-med: {tokens["accent_med"]};
  --gf-accent-line: {tokens["accent_line"]};
  --gf-button-bg: {tokens["button_bg"]};
  --gf-button-border: {tokens["button_border"]};
  --gf-button-hover: {tokens["button_hover"]};
  --gf-button-fg: {tokens["button_fg"]};
  --gf-button-hover-fg: {tokens["button_hover_fg"]};
  --gf-button-active-bg: {tokens["button_active_bg"]};
  --gf-button-active-fg: {tokens["button_active_fg"]};
  --gf-button-primary-fg: {tokens["button_primary_fg"]};
  --gf-button-disabled-bg: {tokens["button_disabled_bg"]};
  --gf-button-disabled-fg: {tokens["button_disabled_fg"]};
  --gf-disabled-bg: {tokens["disabled_bg"]};
  --gf-disabled-fg: {tokens["disabled_fg"]};
  --gf-disabled-border: {tokens["disabled_border"]};
  --gf-focus-ring: {tokens["focus_ring"]};
  --gf-selected-bg: {tokens["selected_bg"]};
  --gf-hover-bg: {tokens["hover_bg"]};
  --gf-active-bg: {tokens["active_bg"]};
  --gf-table-header: {tokens["table_header"]};
  --gf-table-row-alt: {tokens["table_row_alt"]};
  --gf-overlay: {tokens["overlay"]};
  --gf-grad-primary: {tokens["grad_primary"]};
  --gf-grad-primary-hover: {tokens["grad_primary_hover"]};
  --gf-grad-brand: {tokens["grad_brand"]};
  --gf-grad-hero: {tokens["grad_hero"]};
  --gf-grad-surface: {tokens["grad_surface"]};
  --gf-grad-icon: {tokens["grad_icon"]};
  --gf-shadow: {tokens["shadow"]};
  --gf-shadow-md: {tokens["shadow_md"]};
  --gf-shadow-lift: {tokens["shadow_lift"]};
  --gf-glow: {tokens["glow"]};
  --gf-glow-strong: {tokens["glow_strong"]};
  --gf-glass-bg: {tokens["glass_bg"]};
  --gf-glass-border: {tokens["glass_border"]};
}}

.stApp, body {{ background: var(--gf-app-bg) !important; color: var(--gf-fg); }}
[data-testid="stSidebar"] {{
  background: {tokens["sidebar_grad"]} !important;
  border-right-color: var(--gf-border) !important;
  box-shadow: var(--gf-shadow-lift) !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label {{ color: var(--gf-muted); }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{ color: var(--gf-muted) !important; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  background: var(--gf-accent-soft) !important; border-color: var(--gf-border-accent) !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: var(--gf-selected-bg) !important; border-color: var(--gf-border-accent) !important;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: var(--gf-fg) !important; }}
.gf-app-header, .gf-card, .gf-card-accent, .studio-card, .gf-project-card-wrap,
.gf-ai-panel, .gf-row-card, .gf-timeline, .gf-editor-panel {{
  background: var(--gf-card-grad) !important;
  border-color: var(--gf-border) !important;
  color: var(--gf-fg);
  box-shadow: var(--gf-shadow-md);
}}
.gf-brand {{ background-image: var(--gf-grad-brand); }}
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  background: var(--gf-button-bg) !important;
  border-color: var(--gf-button-border) !important;
  color: var(--gf-button-fg) !important;
  box-shadow: var(--gf-shadow) !important;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
  background: var(--gf-button-hover) !important; border-color: var(--gf-border-accent) !important;
  color: var(--gf-button-hover-fg) !important;
}}
.stButton > button:active, .stDownloadButton > button:active, .stFormSubmitButton > button:active {{
  background: var(--gf-button-active-bg) !important;
  color: var(--gf-button-active-fg) !important;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: var(--gf-grad-primary) !important; color: var(--gf-button-primary-fg) !important;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
.stButton > button[kind="primary"]:active, .stFormSubmitButton > button[kind="primary"]:active {{
  color: var(--gf-button-primary-fg) !important;
}}
.stButton > button:disabled, .stDownloadButton > button:disabled,
.stFormSubmitButton > button:disabled {{
  background: var(--gf-button-disabled-bg) !important;
  border-color: var(--gf-disabled-border) !important;
  color: var(--gf-button-disabled-fg) !important;
  opacity: .72 !important;
  box-shadow: none !important;
}}
/* Streamlit renders labels and Material Symbols inside the button.  Reassert
   the button foreground on descendants so the page-level paragraph rule
   cannot turn a readable label into dark text on a dark action surface. */
.stButton > button *, .stDownloadButton > button *, .stFormSubmitButton > button *,
[data-testid="stDeployButton"] button *, [data-testid="stToolbar"] button * {{
  color: inherit !important;
}}
button[data-testid^="btn_open_recent_"] {{
  background: var(--gf-accent-soft) !important;
  border-color: var(--gf-border-accent) !important;
  color: var(--gf-accent-strong) !important;
}}
button[data-testid^="btn_open_recent_"]:hover {{
  background: var(--gf-accent-med) !important;
  color: var(--gf-accent-strong) !important;
}}
button[data-testid^="btn_rename_recent_"] {{
  background: var(--gf-button-bg) !important;
  border-color: var(--gf-button-border) !important;
  color: var(--gf-button-fg) !important;
}}
button[data-testid^="btn_rename_recent_"]:hover {{
  background: var(--gf-button-hover) !important;
  color: var(--gf-button-hover-fg) !important;
}}
button[data-testid^="btn_delete_recent_"] {{
  background: var(--gf-bad-bg) !important;
  border-color: var(--gf-bad-border) !important;
  color: var(--gf-bad) !important;
}}
button[data-testid^="btn_delete_recent_"]:hover {{
  background: var(--gf-bad) !important;
  border-color: var(--gf-bad) !important;
  color: var(--gf-fg-inv) !important;
}}
[data-testid="stDeployButton"] button, [data-testid="stToolbar"] button {{
  background: var(--gf-button-bg) !important;
  border-color: var(--gf-button-border) !important;
  color: var(--gf-button-fg) !important;
}}
[data-testid="stDeployButton"] button:hover, [data-testid="stToolbar"] button:hover {{
  background: var(--gf-button-hover) !important;
  color: var(--gf-button-hover-fg) !important;
}}
/* Streamlit 1.5x+ renders native buttons as stBaseButton-* elements rather
   than descendants of a .stButton wrapper. */
button[data-testid^="stBaseButton-"] {{
  background: var(--gf-button-bg) !important;
  border: 1px solid var(--gf-button-border) !important;
  color: var(--gf-button-fg) !important;
  box-shadow: var(--gf-shadow) !important;
}}
button[data-testid^="stBaseButton-"] * {{ color: inherit !important; }}
button[data-testid^="stBaseButton-"]:hover {{
  background: var(--gf-button-hover) !important;
  border-color: var(--gf-border-accent) !important;
  color: var(--gf-button-hover-fg) !important;
}}
button[data-testid^="stBaseButton-"]:active {{
  background: var(--gf-button-active-bg) !important;
  color: var(--gf-button-active-fg) !important;
}}
button[data-testid="stBaseButton-primary"],
button[data-testid="stBaseButton-primary"]:hover,
button[data-testid="stBaseButton-primary"]:active {{
  background: var(--gf-grad-primary) !important;
  border-color: transparent !important;
  color: var(--gf-button-primary-fg) !important;
}}
button[data-testid^="stBaseButton-"]:disabled {{
  background: var(--gf-button-disabled-bg) !important;
  border-color: var(--gf-disabled-border) !important;
  color: var(--gf-button-disabled-fg) !important;
  opacity: .72 !important;
  box-shadow: none !important;
}}
.stTextInput input, .stTextArea textarea, .stNumberInput input,
[data-baseweb="select"] > div, [data-baseweb="input"] > div {{
  background: var(--gf-input-bg) !important;
  border-color: var(--gf-input-border) !important;
  color: var(--gf-fg) !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus,
[data-baseweb="select"] > div:focus-within, [data-baseweb="input"] > div:focus-within {{
  border-color: var(--gf-accent) !important; box-shadow: 0 0 0 3px var(--gf-focus-ring) !important;
}}
.stTabs [data-baseweb="tab"], .stSelectbox label, .stTextInput label,
.stTextArea label, .stCheckbox label, .stRadio label, .stSlider label {{ color: var(--gf-muted) !important; }}
.stTabs [aria-selected="true"] {{ color: var(--gf-fg) !important; border-bottom-color: var(--gf-accent) !important; }}
button:disabled {{ background: var(--gf-disabled-bg) !important; color: var(--gf-disabled-fg) !important; }}
*:focus-visible {{ outline: 2px solid var(--gf-accent) !important; outline-offset: 2px; }}
.gf-project-card-wrap .gf-pcard-name, .gf-header-center span {{ color: var(--gf-fg) !important; }}
.gf-project-card-wrap .gf-pcard-detail, .gf-project-card-wrap .gf-pcard-id,
.gf-page-note, .gf-project-tag {{ color: var(--gf-muted) !important; }}
.gf-timeline-block, .gf-timeline-track, .gf-editor-canvas {{
  background: var(--gf-editor-bg) !important; border-color: var(--gf-border) !important;
}}
.gf-timeline-block.is-selected, .gf-timeline-block.selected {{
  background: var(--gf-selected-bg) !important; border-color: var(--gf-accent) !important;
}}

/* Native Streamlit controls and shared interaction states.  Keep this final
   layer token-only so older component rules cannot leak the dark palette into
   light mode. */
.stApp, .stApp p, .stApp label, .stApp [data-testid="stMarkdownContainer"] {{ color: var(--gf-fg); }}
.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stDateInput input, [data-baseweb="select"] > div,
[data-baseweb="input"] > div, [data-baseweb="textarea"] {{
  background: var(--gf-input-bg) !important;
  border-color: var(--gf-input-border) !important;
  color: var(--gf-fg) !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder,
.stNumberInput input::placeholder {{ color: var(--gf-muted) !important; opacity: .9; }}
.stMultiSelect [data-baseweb="tag"] {{
  background: var(--gf-selected-bg) !important; color: var(--gf-fg) !important;
}}
[data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {{
  background: var(--gf-s1) !important; border-color: var(--gf-border) !important;
  color: var(--gf-fg) !important;
}}
[role="option"]:hover, [role="option"][aria-selected="true"] {{
  background: var(--gf-selected-bg) !important; color: var(--gf-fg) !important;
}}
.stCheckbox label, .stRadio label, .stSlider label, .stSelectbox label,
.stMultiSelect label, .stFileUploader label, .stDateInput label,
.stNumberInput label, .stTextInput label, .stTextArea label {{ color: var(--gf-muted) !important; }}
.stSlider [data-baseweb="slider"] [role="slider"] {{ background: var(--gf-accent) !important; }}
.stFileUploader, [data-testid="stForm"], [data-testid="stDataFrame"],
[data-testid="stDataEditor"] {{
  background: var(--gf-panel) !important; border-color: var(--gf-border) !important;
  color: var(--gf-fg) !important;
}}
[data-testid="stFileUploader"] section {{
  background: var(--gf-uploader-bg) !important;
  border: 1px dashed var(--gf-uploader-border) !important;
  color: var(--gf-uploader-fg) !important;
}}
[data-testid="stFileUploader"] {{
  background: var(--gf-uploader-bg) !important;
  border-color: var(--gf-uploader-border) !important;
  color: var(--gf-uploader-fg) !important;
}}
[data-testid="stFileUploader"] [data-testid="stWidgetLabel"],
[data-testid="stFileUploader"] [data-testid="stWidgetLabel"] p {{
  color: var(--gf-uploader-fg) !important;
}}
[data-testid="stFileUploaderDropzone"] {{
  background: var(--gf-uploader-bg) !important;
  border-color: var(--gf-uploader-border) !important;
  color: var(--gf-uploader-fg) !important;
}}
[data-testid="stFileUploaderDropzone"]:hover {{
  background: var(--gf-uploader-hover-bg) !important;
  border-color: var(--gf-uploader-hover-border) !important;
}}
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] *,
[data-testid="stFileUploaderDropzoneInstructions"] p {{
  color: var(--gf-uploader-muted) !important;
  -webkit-text-fill-color: var(--gf-uploader-muted) !important;
  opacity: 1 !important;
}}
[data-testid="stFileUploaderDropzone"] [data-testid="stFileUploaderDropzoneInstructions"] > div > span {{
  color: var(--gf-uploader-muted) !important;
  -webkit-text-fill-color: var(--gf-uploader-muted) !important;
  opacity: 1 !important;
}}
[data-testid="stFileUploader"] [data-testid="stIconMaterial"] {{
  color: var(--gf-uploader-icon) !important;
}}
[data-testid="stFileUploader"] button[data-testid^="stBaseButton-"] {{
  background: var(--gf-uploader-button-bg) !important;
  border-color: var(--gf-uploader-border) !important;
  color: var(--gf-uploader-button-fg) !important;
  box-shadow: var(--gf-shadow) !important;
}}
[data-testid="stFileUploader"] button[data-testid^="stBaseButton-"] * {{
  color: inherit !important;
}}
[data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"],
[data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"] *,
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] * {{
  color: var(--gf-uploader-fg) !important;
}}
[data-testid="stFileUploader"] [data-testid="stFileUploaderFileDetails"],
[data-testid="stFileUploader"] [data-testid="stFileUploaderFileDetails"] * {{
  color: var(--gf-uploader-muted) !important;
}}
[data-testid="stFileUploader"] button[aria-label*="Remove"],
[data-testid="stFileUploader"] button[aria-label*="Delete"],
[data-testid="stFileUploader"] button[aria-label*="remove"],
[data-testid="stFileUploader"] button[aria-label*="delete"] {{
  background: transparent !important;
  border-color: transparent !important;
  color: var(--gf-uploader-icon) !important;
  box-shadow: none !important;
}}
[data-testid="stFileUploader"] button[aria-label*="Remove"] *,
[data-testid="stFileUploader"] button[aria-label*="Delete"] *,
[data-testid="stFileUploader"] button[aria-label*="remove"] *,
[data-testid="stFileUploader"] button[aria-label*="delete"] * {{
  color: inherit !important;
}}
[data-testid="stMetric"], [data-testid="stAlert"], details[data-testid="stExpander"] {{
  background: var(--gf-card-grad) !important; border-color: var(--gf-border) !important;
  color: var(--gf-fg) !important;
}}
details[data-testid="stExpander"] summary:hover {{ background: var(--gf-hover-bg) !important; }}
.stTabs [data-baseweb="tab-list"] {{ background: var(--gf-panel) !important; border-color: var(--gf-border) !important; }}
.stTabs [data-baseweb="tab"] {{ color: var(--gf-muted) !important; }}
.stTabs [data-baseweb="tab"]:hover, .stTabs [aria-selected="true"] {{ color: var(--gf-fg) !important; }}
button:hover {{ border-color: var(--gf-border-accent); }}
button:disabled {{ background: var(--gf-disabled-bg) !important; border-color: var(--gf-disabled-border) !important; color: var(--gf-disabled-fg) !important; }}
input[type="checkbox"]:focus-visible, input[type="radio"]:focus-visible,
button:focus-visible, input:focus-visible, textarea:focus-visible {{
  outline: 2px solid var(--gf-accent) !important; outline-offset: 2px;
}}
div[data-testid="stDataFrame"] [role="columnheader"] {{ background: var(--gf-table-header) !important; color: var(--gf-fg) !important; }}
div[data-testid="stDataFrame"] [role="gridcell"] {{ color: var(--gf-fg) !important; border-color: var(--gf-border) !important; }}
.gf-project-card, .gf-row-card, .gf-empty, .gf-canvas-empty, .gf-banner,
.gf-ai-panel, .gf-stage-bar, .gf-editor-panel, .gf-status-bar {{
  color: var(--gf-fg); background-color: var(--gf-panel); border-color: var(--gf-border);
}}
.gf-project-name, .gf-row-title, .gf-canvas-empty-title, .gf-empty-title,
.gf-card-title, .gf-ai-title {{ color: var(--gf-fg) !important; }}
.gf-project-detail, .gf-row-sub, .gf-canvas-empty-hint, .gf-empty-body,
.gf-card-sub, .gf-page-note, .gf-project-tag {{ color: var(--gf-muted) !important; }}
.gf-hero-title, .hero-title {{ background-image: var(--gf-grad-hero) !important; }}
.gf-status-bar {{ background: var(--gf-editor-bg) !important; }}
.gf-banner-ok {{ background: var(--gf-good-bg) !important; border-color: var(--gf-good-border) !important; color: var(--gf-good) !important; }}
.gf-banner-warn {{ background: var(--gf-warn-bg) !important; border-color: var(--gf-warn-border) !important; color: var(--gf-warn) !important; }}
.gf-banner-err {{ background: var(--gf-bad-bg) !important; border-color: var(--gf-bad-border) !important; color: var(--gf-bad) !important; }}
.gf-banner-info {{ background: var(--gf-info-bg) !important; border-color: var(--gf-info-border) !important; color: var(--gf-info) !important; }}
</style>
"""


# ---------------------------------------------------------------------------
# HTML component helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape a string."""
    return _html.escape(str(text))


def card_open(title: str = "", subtitle: str = "", extra_class: str = "") -> str:
    """Open a .gf-card div.  Always pair with card_close()."""
    title_html = f"<div class='gf-card-title'>{_e(title)}</div>" if title else ""
    sub_html   = f"<div class='gf-card-sub'>{_e(subtitle)}</div>" if subtitle else ""
    return f"<div class='gf-card {extra_class}'>{title_html}{sub_html}"


def card_close() -> str:
    return "</div>"


def studio_card_open(title: str = "", subtitle: str = "") -> str:
    """Legacy .studio-card for studio_pages.py compatibility."""
    kicker = f"<div class='gf-kicker'>{_e(subtitle)}</div>" if subtitle else ""
    h3     = f"<h3>{_e(title)}</h3>" if title else ""
    return f"<div class='studio-card'>{kicker}{h3}"


def studio_card_close() -> str:
    return "</div>"


def badge(
    label: str,
    variant: Literal["ok", "warn", "err", "info", "draft"] = "draft",
) -> str:
    """Unified status badge. Replaces gf-status-tag, status-pill, gf-status-chip."""
    return f"<span class='gf-badge gf-badge-{_e(variant)}'>{_e(label)}</span>"


def sys_pill(label: str, online: bool) -> str:
    """Sidebar system status indicator."""
    cls = "gf-sys-pill-on" if online else "gf-sys-pill-off"
    return f"<div class='gf-sys-pill {cls}' role='status' aria-label='{_e(label)}'>{_e(label)}</div>"


def save_chip(
    status: str,
    error: str | None = None,
) -> str:
    """Save-status chip in the top bar.

    status: "saved" | "saving" | "unsaved" | "failed"
    """
    _MAP = {
        "saved":   ("chip-on",   "Saved"),
        "saving":  ("chip-warn", "Saving\u2026"),
        "unsaved": ("",          "Unsaved changes"),
        "failed":  ("chip-off",  "Save failed"),
    }
    chip_class, chip_label = _MAP.get(status, ("", status))
    title_attr = f"title='{_e(error)}'" if error else ""
    return (
        f"<span class='gf-status-chip {chip_class}' "
        f"role='status' aria-atomic='true' aria-live='polite' {title_attr}>"
        f"{_e(chip_label)}</span>"
    )


def project_card_html(
    name: str,
    detail: str,
    status: str,
    project_id_short: str,
) -> str:
    """Rich project card for the Home page project grid."""
    status_lower = status.lower()
    if status_lower == "ready":
        badge_html = badge("READY", "ok")
    elif status_lower == "failed":
        badge_html = badge("FAILED", "err")
    elif status_lower == "processing":
        badge_html = badge("PROCESSING", "warn")
    else:
        badge_html = badge(status.upper(), "draft")

    return (
        f"<div class='gf-project-card'>"
        f"<div class='gf-project-icon'>🎬</div>"
        f"<div class='gf-project-meta'>"
        f"<div class='gf-project-name'>{_e(name)}</div>"
        f"<div class='gf-project-detail'>{_e(detail)}</div>"
        f"</div>"
        f"<div class='gf-project-badge'>"
        f"{badge_html}"
        f"<span class='gf-row-sub'>{_e(project_id_short)}</span>"
        f"</div>"
        f"</div>"
    )


def row_card_html(
    title: str,
    subtitle: str,
    status_label: str,
    status_variant: Literal["ok", "warn", "err", "info", "draft"],
    right_note: str = "",
) -> str:
    """Generic row card (render history, recent projects)."""
    right_note_html = f"<span class='gf-row-sub'>{_e(right_note)}</span>" if right_note else ""
    return (
        f"<div class='gf-row-card'>"
        f"<div><div class='gf-row-title'>{_e(title)}</div>"
        f"<div class='gf-row-sub'>{_e(subtitle)}</div></div>"
        f"<div class='gf-row-side'>"
        f"{badge(status_label, status_variant)}"
        f"{right_note_html}"
        f"</div></div>"
    )


def canvas_empty(
    icon: str = "🎬",
    title: str = "No media yet",
    hint: str = "Upload media and click Render to see your output here.",
) -> str:
    """Empty state for the preview canvas."""
    return (
        f"<div class='gf-canvas-empty'>"
        f"<div class='gf-canvas-empty-icon' aria-hidden='true'>{icon}</div>"
        f"<div class='gf-canvas-empty-title'>{_e(title)}</div>"
        f"<div class='gf-canvas-empty-hint'>{_e(hint)}</div>"
        f"</div>"
    )


def empty_state(
    icon: str,
    title: str,
    body: str = "",
) -> str:
    """Full-page empty state."""
    body_html = f"<div class='gf-empty-body'>{_e(body)}</div>" if body else ""
    return (
        f"<div class='gf-empty'>"
        f"<div class='gf-empty-icon' aria-hidden='true'>{icon}</div>"
        f"<div class='gf-empty-title'>{_e(title)}</div>"
        f"{body_html}"
        f"</div>"
    )


def section_label(text: str) -> str:
    return f"<span class='gf-section-label'>{_e(text)}</span>"


def banner(
    message: str,
    variant: Literal["ok", "warn", "err", "info"] = "info",
    icon: str = "",
) -> str:
    """Inline notification banner (for context-specific feedback)."""
    icon_html = f"<span aria-hidden='true'>{icon}</span>" if icon else ""
    return (
        f"<div class='gf-banner gf-banner-{variant}' role='alert'>"
        f"{icon_html}<span>{_e(message)}</span>"
        f"</div>"
    )


def ai_plan_panel(
    title: str,
    items: list[str],
    animated: bool = True,
) -> str:
    """AI plan review panel showing list of proposed changes."""
    dot_html = "<div class='gf-ai-dot' aria-hidden='true'></div>" if animated else ""
    items_html = "".join(
        f"<div class='gf-ai-plan-item'>"
        f"<span class='gf-ai-plan-check'>✓</span>"
        f"<span>{_e(item)}</span>"
        f"</div>"
        for item in items
    )
    return (
        f"<div class='gf-ai-panel' role='region' aria-label='AI plan'>"
        f"<div class='gf-ai-panel-header'>{dot_html}"
        f"<span class='gf-ai-title'>{_e(title)}</span></div>"
        f"{items_html}</div>"
    )


def stage_bar(
    stages: list[str],
    current: int = -1,
    completed: int = -1,
    error: int = -1,
) -> str:
    """Render pipeline stage progress bar."""
    items = []
    for i, name in enumerate(stages):
        if i == error:
            cls = "error"
        elif i <= completed:
            cls = "done"
        elif i == current:
            cls = "active"
        else:
            cls = ""
        items.append(
            f"<div class='gf-stage-step {cls}'>{_e(name)}</div>"
        )
        if i < len(stages) - 1:
            items.append("<span style='color:var(--gf-faint);font-size:.7rem;'>›</span>")
    return f"<div class='gf-stage-bar' role='progressbar'>" + "".join(items) + "</div>"


def timeline_track_html(blocks: list[str]) -> str:
    """Wrap pre-built block HTML in the timeline track container."""
    ruler = (
        "<div class='gf-timeline-ruler'>"
        "<span>00:00</span>"
        "<span>EDITORIAL SEQUENCE</span>"
        "<span>END</span>"
        "</div>"
    )
    track = (
        f"<div class='gf-timeline-track' role='list' aria-label='Timeline clips'>"
        + "".join(blocks) + "</div>"
    )
    return ruler + track


def timeline_block_html(
    position: int,
    label: str,
    role: str,
    trim_start: float,
    trim_end: float,
    selected: bool = False,
) -> str:
    """Single clip block for the timeline track."""
    sel = " selected" if selected else ""
    trim_str = f"{trim_start:.1f}s–{trim_end:.1f}s"
    aria_sel = "true" if selected else "false"
    return (
        f"<div class='gf-timeline-block{sel}' role='listitem' aria-selected='{aria_sel}'>"
        f"<strong>{position:02d}</strong>"
        f"<span>{_e(label)}</span>"
        f"<small>{_e(role)} · {trim_str}</small>"
        f"</div>"
    )
