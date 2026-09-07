"""
Test script to verify CSS integration and component rendering.
Tests all key UI components and CSS classes.
"""

import sys
sys.path.insert(0, '.')

from ui_components import (
    get_design_system_css,
    card_open, card_close,
    studio_card_open, studio_card_close,
    badge, sys_pill, save_chip,
    project_card_html, row_card_html,
    canvas_empty, empty_state,
    section_label,
    banner,
    ai_plan_panel,
    stage_bar,
    timeline_track_html, timeline_block_html,
)

def test_css_generation():
    """Test that CSS generates without errors."""
    print("Testing CSS generation...")
    css = get_design_system_css()
    
    # Check CSS size is reasonable
    assert len(css) > 40000, f"CSS too small: {len(css)} chars"
    assert len(css) < 70000, f"CSS suspiciously large: {len(css)} chars"
    
    # Check for key CSS classes
    required_classes = [
        '.gf-card',
        '.gf-badge',
        '.gf-hero-title',
        '.gf-timeline-block',
        '.gf-status-chip',
        '.gf-brand',
        '.stButton > button[kind="primary"]',
        '.stApp',
        '[data-testid="stSidebar"]',
    ]
    
    for cls in required_classes:
        assert cls in css, f"Missing CSS class: {cls}"
    
    # Check for animation keyframes
    assert '@keyframes gfFadeUp' in css
    assert '@keyframes gfPulse' in css
    assert '@keyframes gfShimmer' in css
    
    # Check for color values from _css_addition.txt
    assert '#070A0E' in css, "Deep background color not found"
    assert '#0E1218' in css, "Surface color not found"
    assert '#6366F1' in css, "Accent color not found"
    
    # Check for ripple effect
    assert 'button[kind="primary"]::after' in css
    assert 'radial-gradient(circle at center' in css
    
    # Check for accessibility
    assert ':focus-visible' in css
    assert 'prefers-reduced-motion' in css
    
    print(f"✓ CSS generation passed ({len(css)} characters)")


def test_component_functions():
    """Test that all component functions work."""
    print("\nTesting component functions...")
    
    # Test card
    html = card_open("Test Card", "Subtitle")
    assert "gf-card" in html
    assert "Test Card" in html
    
    # Test badge
    html = badge("READY", "ok")
    assert "gf-badge" in html
    assert "gf-badge-ok" in html
    assert "READY" in html
    
    # Test sys_pill
    html = sys_pill("AI Online", True)
    assert "gf-sys-pill-on" in html
    assert "AI Online" in html
    
    # Test save_chip
    html = save_chip("saved")
    assert "gf-status-chip" in html
    assert "chip-on" in html
    
    # Test project_card_html
    html = project_card_html("My Project", "Video • 1920x1080", "ready", "abc123")
    assert "gf-project-card" in html
    assert "My Project" in html
    assert "abc123" in html
    
    # Test row_card_html
    html = row_card_html("Title", "Subtitle", "READY", "ok", "ID")
    assert "gf-row-card" in html
    assert "Title" in html
    
    # Test canvas_empty
    html = canvas_empty("🎬", "No media", "Upload to begin")
    assert "gf-canvas-empty" in html
    assert "No media" in html
    
    # Test empty_state
    html = empty_state("📁", "No projects", "Create your first project")
    assert "gf-empty" in html
    assert "No projects" in html
    
    # Test section_label
    html = section_label("SETTINGS")
    assert "gf-section-label" in html
    assert "SETTINGS" in html
    
    # Test banner
    html = banner("Operation successful", "ok", "✓")
    assert "gf-banner" in html
    assert "gf-banner-ok" in html
    
    # Test ai_plan_panel
    html = ai_plan_panel("AI Analysis", ["Step 1", "Step 2"])
    assert "gf-ai-panel" in html
    assert "Step 1" in html
    
    # Test stage_bar
    html = stage_bar(["Stage 1", "Stage 2"], current=0)
    assert "gf-stage-bar" in html
    assert "Stage 1" in html
    
    # Test timeline
    block = timeline_block_html(1, "Clip 1", "video", 0.0, 5.0)
    assert "gf-timeline-block" in block
    assert "Clip 1" in block
    
    html = timeline_track_html([block])
    assert "gf-timeline-track" in html
    
    print("✓ All component functions passed")


def test_css_selectors():
    """Test that key CSS selectors are present."""
    print("\nTesting CSS selectors...")
    css = get_design_system_css()
    
    # Test button selectors
    assert '.stButton > button:hover' in css
    assert '.stButton > button[kind="primary"]' in css
    assert '.stButton > button[kind="primary"]:active::after' in css
    
    # Test input selectors
    assert '.stTextInput input' in css
    assert '.stTextInput input:focus' in css
    
    # Test sidebar selectors
    assert '[data-testid="stSidebar"]' in css
    assert '[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked)' in css
    
    # Test tab selectors
    assert '.stTabs [data-baseweb="tab"]' in css
    assert '.stTabs [aria-selected="true"]' in css
    
    # Test responsive breakpoints
    assert '@media (max-width:1100px)' in css
    assert '@media (max-width:900px)' in css
    assert '@media (max-width:760px)' in css
    
    print("✓ All CSS selectors present")


def test_color_consistency():
    """Test that colors from _css_addition.txt are integrated."""
    print("\nTesting color consistency...")
    css = get_design_system_css()
    
    # Background colors (deeper from _css_addition.txt)
    assert '#070A0E' in css, "App background should be #070A0E"
    assert '#0A0D12' in css, "Sidebar background should be #0A0D12"
    
    # Surface colors
    assert '#0E1218' in css, "Surface 1 should be #0E1218"
    assert '#111520' in css, "Surface 2 should be #111520"
    
    # Accent colors
    assert '#6366F1' in css, "Primary accent"
    assert '#818CF8' in css, "Secondary accent"
    
    # Text colors
    assert '#F0F4FF' in css or '#E8ECF3' in css, "Primary text color"
    
    # Border colors
    assert '#1E2A38' in css or '#1A2232' in css, "Border colors present"
    
    print("✓ Color consistency validated")


def test_typography():
    """Test typography enhancements."""
    print("\nTesting typography...")
    css = get_design_system_css()
    
    # Font families
    assert 'Inter' in css
    assert 'JetBrains Mono' in css
    
    # Monospace class
    assert '.gf-mono' in css or 'gf-mono' in css
    
    # Font sizes
    assert '.82rem' in css or '.83rem' in css  # Button text
    assert '.78rem' in css  # Tab text
    
    print("✓ Typography validated")


def test_animations():
    """Test animation keyframes."""
    print("\nTesting animations...")
    css = get_design_system_css()
    
    keyframes = ['gfFadeUp', 'gfFadeIn', 'gfSlideInLeft', 'gfPulse', 'gfShimmer']
    for kf in keyframes:
        assert f'@keyframes {kf}' in css, f"Missing keyframe: {kf}"
    
    # Reduced motion
    assert '@media (prefers-reduced-motion: reduce)' in css
    assert 'animation: none !important' in css
    
    print("✓ Animations validated")


if __name__ == "__main__":
    print("=" * 70)
    print("GENFORGE CSS Integration Test Suite")
    print("=" * 70)
    
    try:
        test_css_generation()
        test_component_functions()
        test_css_selectors()
        test_color_consistency()
        test_typography()
        test_animations()
        
        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nIntegration Summary:")
        print("  • Enhanced color palette integrated")
        print("  • Improved button ripple effect active")
        print("  • Refined typography applied")
        print("  • Better sidebar styling active")
        print("  • Enhanced animations present")
        print("  • All component functions working")
        print("  • Accessibility features validated")
        print("\nThe application should now display the enhanced visual design.")
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
