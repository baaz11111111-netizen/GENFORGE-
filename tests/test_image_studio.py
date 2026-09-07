"""Phase 7 — Advanced image studio regression tests."""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from image_agent import composite_on_background
from services.image_studio import (
    BACKGROUND_COLOR_PRESETS,
    CROP_PRESETS,
    GRADIENT_PRESETS,
    SOCIAL_IMAGE_PRESETS,
    adjust_foreground,
    compose_advanced,
    crop_to_preset,
    make_gradient_background,
    place_subject,
    refine_edges,
)


@pytest.fixture
def cutout(tmp_path):
    """Opaque white subject disc on a fully transparent canvas."""
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 60, 140, 140), fill=(255, 255, 255, 255))
    path = tmp_path / "cutout.png"
    image.save(path, format="PNG")
    return str(path)


class TestGradients:
    def test_all_gradient_presets_render(self):
        for name, (a, b) in GRADIENT_PRESETS.items():
            img = make_gradient_background((40, 40), a, b)
            assert img.size == (40, 40)

    def test_vertical_gradient_endpoints(self):
        img = make_gradient_background((10, 50), "#FF0000", "#0000FF")
        assert img.getpixel((5, 0))[:3] == (255, 0, 0)
        assert img.getpixel((5, 49))[:3] == (0, 0, 255)

    def test_horizontal_gradient_endpoints(self):
        img = make_gradient_background((50, 10), "#FF0000", "#0000FF", "horizontal")
        assert img.getpixel((0, 5))[:3] == (255, 0, 0)
        assert img.getpixel((49, 5))[:3] == (0, 0, 255)

    def test_invalid_hex_rejected(self):
        with pytest.raises(ValueError, match="Invalid HEX"):
            make_gradient_background((10, 10), "#XYZ", "#000000")

    def test_unknown_direction_rejected(self):
        with pytest.raises(ValueError, match="direction"):
            make_gradient_background((10, 10), "#FF0000", "#0000FF", "spiral")


class TestComposeAdvanced:
    def test_gradient_background_pixels(self, cutout, tmp_path):
        out = compose_advanced(cutout, str(tmp_path / "g.png"), gradient=("#FF0000", "#0000FF"),
                               canvas_size=(200, 200), scale=0.3)
        img = Image.open(out)
        assert img.mode == "RGB"
        assert img.getpixel((3, 0)) == (255, 0, 0)
        assert img.getpixel((3, 199)) == (0, 0, 255)

    def test_solid_color_preset_matches_hex_backend(self, cutout, tmp_path):
        out = compose_advanced(cutout, str(tmp_path / "s.png"), background="#00FF00", canvas_size=(200, 200), scale=0.3)
        reference = composite_on_background(cutout, "#00FF00", str(tmp_path / "ref.png"))
        pixel_new = Image.open(out).getpixel((2, 2))
        pixel_ref = Image.open(reference).getpixel((2, 2))
        assert pixel_new == pixel_ref == (0, 255, 0)

    def test_transparent_background_keeps_alpha(self, cutout, tmp_path):
        out = compose_advanced(cutout, str(tmp_path / "t.png"), background="transparent")
        img = Image.open(out)
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0

    def test_eight_digit_hex_alpha_survives(self, cutout, tmp_path):
        out = compose_advanced(cutout, str(tmp_path / "a.png"), background="#FF000080", canvas_size=(200, 200), scale=0.3)
        img = Image.open(out)
        assert img.mode == "RGBA"
        assert img.getpixel((2, 2)) == (255, 0, 0, 128)

    def test_image_background_supported(self, cutout, tmp_path):
        bg = Image.new("RGB", (300, 300), (10, 20, 30))
        bg_path = tmp_path / "bg.png"
        bg.save(bg_path)
        out = compose_advanced(cutout, str(tmp_path / "o.png"), background=str(bg_path),
                               canvas_size=(200, 200), scale=0.3)
        assert Image.open(out).getpixel((2, 2)) == (10, 20, 30)

    def test_subject_scale_changes_footprint(self, cutout, tmp_path):
        small = compose_advanced(cutout, str(tmp_path / "sm.png"), background="#0000FF",
                                 canvas_size=(200, 200), scale=0.2)
        large = compose_advanced(cutout, str(tmp_path / "lg.png"), background="#0000FF",
                                 canvas_size=(200, 200), scale=1.5)
        center_small = Image.open(small).getpixel((100, 60))
        center_large = Image.open(large).getpixel((100, 60))
        assert center_small == (0, 0, 255)          # small subject does not reach y=60
        assert center_large != (0, 0, 255)          # large subject does

    def test_subject_position_moves_center(self, cutout, tmp_path):
        left = compose_advanced(cutout, str(tmp_path / "l.png"), background="#0000FF",
                                canvas_size=(200, 200), scale=0.5, position=(0.0, 0.5))
        right = compose_advanced(cutout, str(tmp_path / "r.png"), background="#0000FF",
                                 canvas_size=(200, 200), scale=0.5, position=(1.0, 0.5))
        assert Image.open(left).getpixel((10, 100)) != (0, 0, 255)
        assert Image.open(right).getpixel((190, 100)) != (0, 0, 255)

    def test_shadow_darkens_area_below_subject(self, cutout, tmp_path):
        with_shadow = compose_advanced(cutout, str(tmp_path / "sh.png"), background="#FFFFFF",
                                       canvas_size=(200, 200), scale=0.5, position=(0.5, 0.4), shadow=True)
        without = compose_advanced(cutout, str(tmp_path / "nosh.png"), background="#FFFFFF",
                                   canvas_size=(200, 200), scale=0.5, position=(0.5, 0.4), shadow=False)
        shadow_pixel = Image.open(with_shadow).getpixel((100, 133))
        plain_pixel = Image.open(without).getpixel((100, 133))
        assert sum(shadow_pixel) < sum(plain_pixel)

    def test_social_canvas_presets_exact_size(self, cutout, tmp_path):
        out = compose_advanced(cutout, str(tmp_path / "ig.png"), background="#FFFFFF",
                               canvas_size=SOCIAL_IMAGE_PRESETS["Instagram Post"], scale=0.5)
        assert Image.open(out).size == (1080, 1080)

    def test_invalid_scale_rejected(self, cutout, tmp_path):
        with pytest.raises(ValueError, match="scale"):
            compose_advanced(cutout, str(tmp_path / "x.png"), scale=9.0)


class TestEdgeRefinement:
    def test_feather_creates_semitransparent_edge(self, cutout):
        image = Image.open(cutout)
        feathered = refine_edges(image, feather=4.0)
        alphas = {feathered.getpixel((x, 100))[3] for x in range(55, 66)}
        assert any(0 < a < 255 for a in alphas)

    def test_erode_shrinks_subject(self, cutout):
        image = Image.open(cutout)
        eroded = refine_edges(image, erode=3)
        assert eroded.getpixel((61, 100))[3] < image.getpixel((61, 100))[3]

    def test_negative_values_rejected(self, cutout):
        with pytest.raises(ValueError):
            refine_edges(Image.open(cutout), feather=-1)


class TestForegroundAdjustment:
    def test_brightness_change(self, cutout):
        image = Image.open(cutout)
        darker = adjust_foreground(image, brightness=0.4)
        assert darker.getpixel((100, 100))[0] < image.getpixel((100, 100))[0]

    def test_alpha_preserved(self, cutout):
        adjusted = adjust_foreground(Image.open(cutout), saturation=2.0)
        assert adjusted.getpixel((0, 0))[3] == 0

    def test_bounds(self, cutout):
        with pytest.raises(ValueError):
            adjust_foreground(Image.open(cutout), contrast=9.0)


class TestCropPresets:
    def test_every_preset_ratio(self, tmp_path):
        source = tmp_path / "src.png"
        Image.new("RGB", (400, 300), (1, 2, 3)).save(source)
        for name, (rw, rh) in CROP_PRESETS.items():
            out = crop_to_preset(str(source), name, str(tmp_path / f"{name.replace(' ', '_')}.png"))
            img = Image.open(out)
            assert abs(img.width / img.height - rw / rh) < 0.02

    def test_unknown_preset_rejected(self, tmp_path):
        source = tmp_path / "src.png"
        Image.new("RGB", (100, 100)).save(source)
        with pytest.raises(ValueError, match="Unknown crop preset"):
            crop_to_preset(str(source), "Banana", str(tmp_path / "x.png"))


class TestColorPresets:
    def test_every_color_preset_is_valid_hex(self):
        from image_agent import validate_hex_color
        for name, hex_value in BACKGROUND_COLOR_PRESETS.items():
            assert validate_hex_color(hex_value), name

    def test_place_subject_rejects_bad_position(self):
        canvas = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        subject = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
        with pytest.raises(ValueError, match="position"):
            place_subject(canvas, subject, position=(1.5, 0.5))
