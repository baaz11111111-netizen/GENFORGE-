"""
Image Background Removal + Color Replacement — Pixel-Level Regression Tests.

Section 27 compliance: these tests verify ACTUAL FINAL IMAGE PIXELS,
not merely UI state.

A synthetic RGBA cutout is created for each test: a white square
"subject" (alpha=255) centred on a fully transparent border (alpha=0).
This mirrors the output that rembg would produce and lets us verify
the compositing pipeline deterministically without the rembg dependency.
"""
import os
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cutout(path: Path, size: int = 100, subject_size: int = 40) -> Path:
    """Creates a synthetic RGBA cutout:
    - Canvas: size x size, fully transparent (0,0,0,0)
    - Subject: centred subject_size x subject_size, opaque white (255,255,255,255)
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - subject_size) // 2
    for y in range(offset, offset + subject_size):
        for x in range(offset, offset + subject_size):
            img.putpixel((x, y), (255, 255, 255, 255))
    img.save(str(path), format="PNG")
    return path


def _make_rgb_source(path: Path, size: int = 100) -> Path:
    """Creates a plain RGB image (no alpha)."""
    img = Image.new("RGB", (size, size), (128, 128, 128))
    img.save(str(path), format="PNG")
    return path


def _make_rgba_source(path: Path, size: int = 100) -> Path:
    """Creates an RGBA image with partial alpha."""
    img = Image.new("RGBA", (size, size), (100, 150, 200, 200))
    img.save(str(path), format="PNG")
    return path


def _corner_pixel(img: Image.Image):
    """Returns the top-left pixel, which is always in the transparent border."""
    return img.getpixel((0, 0))


def _center_pixel(img: Image.Image):
    """Returns the centre pixel, which is always in the opaque subject."""
    cx, cy = img.size[0] // 2, img.size[1] // 2
    return img.getpixel((cx, cy))


# ---------------------------------------------------------------------------
# Import the functions under test
# ---------------------------------------------------------------------------
from image_agent import (
    composite_on_background,
    validate_hex_color,
    hex_to_rgba,
    remove_image_background,
    HAS_REMBG,
)


# ===========================================================================
# 1. Background removal raises when rembg is unavailable
# ===========================================================================
class TestBackgroundRemoval:
    def test_remove_background_requires_rembg(self, tmp_path):
        """If rembg is not installed the function must raise, not fake success."""
        source = tmp_path / "source.png"
        _make_rgb_source(source)
        out = tmp_path / "cutout.png"

        if not HAS_REMBG:
            with pytest.raises(RuntimeError, match="rembg"):
                remove_image_background(str(source), str(out))
        else:
            # If rembg IS installed, function should succeed
            result = remove_image_background(str(source), str(out))
            assert Path(result).is_file()


# ===========================================================================
# 2. Transparent export preserves alpha
# ===========================================================================
class TestTransparentExport:
    def test_transparent_export_preserves_alpha(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "result.png"

        result = composite_on_background(str(cutout), "transparent", str(out))
        img = Image.open(result)

        assert img.mode == "RGBA", "Transparent export must be RGBA"
        corner = _corner_pixel(img)
        assert corner[3] == 0, f"Corner alpha should be 0, got {corner[3]}"


# ===========================================================================
# 3. White background produces white pixels outside the foreground
# ===========================================================================
class TestWhiteBackground:
    def test_white_background_produces_white_pixels(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "white_bg.png"

        result = composite_on_background(str(cutout), "white", str(out))
        img = Image.open(result)

        corner = _corner_pixel(img)
        assert corner[0] == 255 and corner[1] == 255 and corner[2] == 255, (
            f"Expected white corner pixel (255,255,255), got {corner[:3]}"
        )


# ===========================================================================
# 4. Black background produces black pixels
# ===========================================================================
class TestBlackBackground:
    def test_black_background_produces_black_pixels(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "black_bg.png"

        result = composite_on_background(str(cutout), "black", str(out))
        img = Image.open(result)

        corner = _corner_pixel(img)
        assert corner[0] == 0 and corner[1] == 0 and corner[2] == 0, (
            f"Expected black corner pixel (0,0,0), got {corner[:3]}"
        )


# ===========================================================================
# 5. Custom HEX background works
# ===========================================================================
class TestCustomHexBackground:
    def test_custom_hex_background(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "red_bg.png"

        result = composite_on_background(str(cutout), "#FF0000", str(out))
        img = Image.open(result)

        corner = _corner_pixel(img)
        assert corner[0] == 255 and corner[1] == 0 and corner[2] == 0, (
            f"Expected red corner pixel (255,0,0), got {corner[:3]}"
        )


# ===========================================================================
# 6. Invalid HEX is rejected
# ===========================================================================
class TestHexValidation:
    def test_invalid_hex_is_rejected(self):
        assert validate_hex_color("#FFFFFF") is True
        assert validate_hex_color("#FFF") is True
        assert validate_hex_color("#FF00FF80") is True  # RGBA hex
        assert validate_hex_color("FFFFFF") is False     # no hash
        assert validate_hex_color("#GGG") is False        # invalid chars
        assert validate_hex_color("#12") is False         # too short
        assert validate_hex_color("") is False
        assert validate_hex_color("#12345") is False      # bad length


# ===========================================================================
# 7. Changing color updates output
# ===========================================================================
class TestColorChangeUpdatesOutput:
    def test_changing_color_updates_output(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")

        # First: white background
        out1 = tmp_path / "white.png"
        composite_on_background(str(cutout), "white", str(out1))
        img1 = Image.open(str(out1))
        corner1 = _corner_pixel(img1)

        # Second: red background
        out2 = tmp_path / "red.png"
        composite_on_background(str(cutout), "#FF0000", str(out2))
        img2 = Image.open(str(out2))
        corner2 = _corner_pixel(img2)

        assert corner1[:3] != corner2[:3], (
            "Changing color must produce different pixels"
        )


# ===========================================================================
# 8. Resetting to transparent works
# ===========================================================================
class TestResetToTransparent:
    def test_resetting_to_transparent_works(self, tmp_path):
        cutout = _make_cutout(tmp_path / "cutout.png")

        # First: solid color
        out1 = tmp_path / "solid.png"
        composite_on_background(str(cutout), "white", str(out1))
        img1 = Image.open(str(out1))

        # Second: transparent
        out2 = tmp_path / "transparent.png"
        composite_on_background(str(cutout), "transparent", str(out2))
        img2 = Image.open(str(out2))

        assert img2.mode == "RGBA"
        corner = _corner_pixel(img2)
        assert corner[3] == 0, (
            f"After reset to transparent, corner alpha should be 0, got {corner[3]}"
        )


# ===========================================================================
# 9. RGBA source works
# ===========================================================================
class TestRGBASource:
    def test_rgba_source_works(self, tmp_path):
        """An RGBA source image must be processed correctly."""
        source = tmp_path / "rgba_source.png"
        _make_rgba_source(source, size=80)

        # Build a cutout from the RGBA source (simulated: just use it directly as cutout)
        out = tmp_path / "rgba_result.png"
        result = composite_on_background(str(source), "#00FF00", str(out))
        img = Image.open(result)

        assert img.size == (80, 80)
        assert img.mode in ("RGB", "RGBA")


# ===========================================================================
# 10. RGB source works
# ===========================================================================
class TestRGBSource:
    def test_rgb_source_works(self, tmp_path):
        """An RGB (no alpha) source image must be processed correctly."""
        source = tmp_path / "rgb_source.png"
        _make_rgb_source(source, size=80)

        out = tmp_path / "rgb_result.png"
        result = composite_on_background(str(source), "#0000FF", str(out))
        img = Image.open(result)

        assert img.size == (80, 80)
        assert img.mode in ("RGB", "RGBA")


# ===========================================================================
# Additional: hex_to_rgba correctness
# ===========================================================================
class TestHexToRGBA:
    def test_hex_to_rgba_conversions(self):
        assert hex_to_rgba("#FFFFFF") == (255, 255, 255, 255)
        assert hex_to_rgba("#000000") == (0, 0, 0, 255)
        assert hex_to_rgba("#FF0000") == (255, 0, 0, 255)
        assert hex_to_rgba("#F00") == (255, 0, 0, 255)  # short form
        assert hex_to_rgba("#FF000080") == (255, 0, 0, 128)  # RGBA

    def test_hex_to_rgba_rejects_invalid(self):
        with pytest.raises(ValueError):
            hex_to_rgba("#GGGGGG")
        with pytest.raises(ValueError):
            hex_to_rgba("not-a-color")


# ===========================================================================
# Additional: 8-digit RGBA HEX compositing (mandate item 6 — UI/backend parity)
# ===========================================================================
class TestEightDigitHexCompositing:
    def test_composite_with_8_digit_rgba_hex(self, tmp_path):
        """#FF000080 (red, alpha 128) must be accepted by the compositing
        backend — the historical gap where validate_hex_color accepted it but
        parse_color_to_rgba raised ValueError."""
        from image_agent import parse_color_to_rgba

        assert parse_color_to_rgba("#FF000080") == (255, 0, 0, 128)

        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "semi_red.png"
        result = composite_on_background(str(cutout), "#FF000080", str(out))
        img = Image.open(result)

        # Semi-transparent background must stay RGBA so alpha survives export
        assert img.mode == "RGBA", f"Semi-transparent bg must export as RGBA, got {img.mode}"
        corner = _corner_pixel(img)
        # alpha_composite of opaque red@128 over transparent yields alpha=128
        assert corner == (255, 0, 0, 128), f"Expected (255,0,0,128), got {corner}"

    def test_composite_with_fully_transparent_8_digit_hex(self, tmp_path):
        """#FF000000 (alpha 0) must produce a fully transparent export."""
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "alpha_zero.png"
        result = composite_on_background(str(cutout), "#FF000000", str(out))
        img = Image.open(result)
        assert img.mode == "RGBA"
        corner = _corner_pixel(img)
        assert corner[3] == 0, f"Alpha-0 background must yield alpha 0, got {corner[3]}"

    def test_arbitrary_hex_color(self, tmp_path):
        """Arbitrary 6-digit HEX (#12AB3C) must affect actual output pixels."""
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "arbitrary.png"
        result = composite_on_background(str(cutout), "#12AB3C", str(out))
        img = Image.open(result)
        corner = _corner_pixel(img)
        assert corner[:3] == (0x12, 0xAB, 0x3C), f"Expected (18,171,60), got {corner[:3]}"

    def test_three_digit_hex_color(self, tmp_path):
        """3-digit short HEX (#00F) must expand and affect actual output pixels."""
        cutout = _make_cutout(tmp_path / "cutout.png")
        out = tmp_path / "short_hex.png"
        result = composite_on_background(str(cutout), "#00F", str(out))
        img = Image.open(result)
        corner = _corner_pixel(img)
        assert corner[:3] == (0, 0, 255), f"Expected (0,0,255) from #00F, got {corner[:3]}"

    def test_multiple_color_changes_red_to_blue(self, tmp_path):
        """Red -> Blue -> Green sequence must change actual output pixels each time."""
        cutout = _make_cutout(tmp_path / "cutout.png")
        corners = []
        for name, hex_val in [("red", "#FF0000"), ("blue", "#0000FF"), ("green", "#00FF00")]:
            out = tmp_path / f"{name}.png"
            composite_on_background(str(cutout), hex_val, str(out))
            corners.append(_corner_pixel(Image.open(str(out)))[:3])
        assert corners[0] == (255, 0, 0)
        assert corners[1] == (0, 0, 255)
        assert corners[2] == (0, 255, 0)
        assert len(set(corners)) == 3, "Each color change must produce distinct pixels"
