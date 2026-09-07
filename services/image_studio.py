"""Advanced image studio: gradients, shadows, edge refinement, subject placement.

Extends the existing image_agent background pipeline — transparent / solid
color / image backgrounds and full HEX parity (#RGB, #RRGGBB, #RRGGBBAA) keep
working exactly as before. Everything here is deterministic PIL compositing.
"""

from __future__ import annotations

import os
from typing import Tuple

from PIL import Image, ImageEnhance, ImageFilter

from image_agent import hex_to_rgba, parse_color_to_rgba, validate_hex_color

BACKGROUND_COLOR_PRESETS: dict[str, str] = {
    "Studio White": "#FFFFFF",
    "Jet Black": "#0A0A0A",
    "Brand Red": "#FF3B30",
    "Electric Blue": "#0A84FF",
    "Mint": "#34C759",
    "Sunshine": "#FFD60A",
    "Royal Purple": "#5E5CE6",
    "Neutral Gray": "#8E8E93",
}

GRADIENT_PRESETS: dict[str, Tuple[str, str]] = {
    "Sunset": ("#FF512F", "#DD2476"),
    "Ocean": ("#2E3192", "#1BFFFF"),
    "Gold Hour": ("#F7971E", "#FFD200"),
    "Northern Sky": ("#43C6AC", "#191654"),
    "Mono Fade": ("#232526", "#7A7F83"),
}

GRADIENT_DIRECTIONS = ("vertical", "horizontal", "diagonal")

SOCIAL_IMAGE_PRESETS: dict[str, Tuple[int, int]] = {
    "Instagram Post": (1080, 1080),
    "Instagram Story": (1080, 1920),
    "YouTube Thumbnail": (1280, 720),
    "X Card": (1200, 675),
    "Facebook Cover": (1640, 624),
    "LinkedIn Banner": (1584, 396),
}

CROP_PRESETS: dict[str, Tuple[int, int]] = {
    "Square 1:1": (1, 1),
    "Portrait 4:5": (4, 5),
    "Vertical 9:16": (9, 16),
    "Landscape 16:9": (16, 9),
    "Classic 3:2": (3, 2),
}


def _validated_hex(color: str) -> Tuple[int, int, int, int]:
    if not validate_hex_color(color):
        raise ValueError(f"Invalid HEX color: {color}")
    return hex_to_rgba(color)


def make_gradient_background(
    size: Tuple[int, int],
    color_a: str,
    color_b: str,
    direction: str = "vertical",
) -> Image.Image:
    """Render a two-stop linear gradient as an RGBA background layer.

    Uses numpy broadcasting for a vectorized fill — several orders of magnitude
    faster than the previous per-pixel Python loop on large canvases.
    """
    import numpy as np

    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("Gradient size must be positive.")
    if direction not in GRADIENT_DIRECTIONS:
        raise ValueError(f"Unknown gradient direction '{direction}'. Available: {', '.join(GRADIENT_DIRECTIONS)}")
    start = np.array(_validated_hex(color_a)[:3], dtype=np.float32)
    stop  = np.array(_validated_hex(color_b)[:3], dtype=np.float32)

    if direction == "vertical":
        # fraction varies along Y axis: shape (H, 1)
        fraction = np.linspace(0.0, 1.0, height, dtype=np.float32).reshape(height, 1)
    elif direction == "horizontal":
        # fraction varies along X axis: shape (1, W)
        fraction = np.linspace(0.0, 1.0, width, dtype=np.float32).reshape(1, width)
    else:  # diagonal
        fy = np.linspace(0.0, 1.0, height, dtype=np.float32).reshape(height, 1)
        fx = np.linspace(0.0, 1.0, width, dtype=np.float32).reshape(1, width)
        fraction = (fy + fx) / 2.0

    # Broadcast interpolation to (H, W, 3) — fraction may be (H,1) or (1,W)
    # so we must expand it to the full canvas shape before adding the alpha.
    rgb_broadcast = np.round(start + (stop - start) * fraction[..., np.newaxis]).astype(np.float32)
    # np.broadcast_to returns a read-only view; copy to get a writable (H, W, 3) array.
    rgb = np.broadcast_to(rgb_broadcast, (height, width, 3)).astype(np.uint8)

    # Append full-opacity alpha channel: (H, W, 4)
    alpha = np.full((height, width, 1), 255, dtype=np.uint8)
    rgba = np.concatenate([rgb, alpha], axis=2)

    return Image.fromarray(rgba, mode="RGBA")


def refine_edges(cutout: Image.Image, feather: float = 0.0, erode: int = 0) -> Image.Image:
    """Soften (feather) and tighten (erode) the cutout alpha edge."""
    if feather < 0 or erode < 0:
        raise ValueError("feather and erode cannot be negative.")
    if cutout.mode != "RGBA":
        raise ValueError("Edge refinement requires an RGBA cutout.")
    result = cutout.copy()
    if erode:
        alpha = result.getchannel("A")
        for _ in range(erode):
            alpha = alpha.filter(ImageFilter.MinFilter(3))
        result.putalpha(alpha)
    if feather:
        alpha = result.getchannel("A").filter(ImageFilter.GaussianBlur(feather))
        result.putalpha(alpha)
    return result


def adjust_foreground(cutout: Image.Image, brightness: float = 1.0, contrast: float = 1.0, saturation: float = 1.0) -> Image.Image:
    """Brightness/contrast/saturation on the subject while preserving alpha."""
    if cutout.mode != "RGBA":
        raise ValueError("Foreground adjustment requires an RGBA cutout.")
    for name, value in (("brightness", brightness), ("contrast", contrast), ("saturation", saturation)):
        if not 0.0 <= value <= 4.0:
            raise ValueError(f"{name} must be between 0.0 and 4.0.")
    alpha = cutout.getchannel("A")
    rgb = cutout.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Color(rgb).enhance(saturation)
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def add_subject_shadow(
    canvas: Image.Image,
    cutout: Image.Image,
    subject_box: Tuple[int, int, int, int],
    offset: Tuple[int, int] = (0, 14),
    blur: float = 12.0,
    opacity: int = 140,
) -> Image.Image:
    """Composite a blurred drop shadow of the subject silhouette onto canvas."""
    if not 0 <= opacity <= 255:
        raise ValueError("Shadow opacity must be between 0 and 255.")
    if blur < 0:
        raise ValueError("Shadow blur cannot be negative.")
    left, top, right, bottom = subject_box
    silhouette = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    alpha = cutout.getchannel("A").resize((max(1, right - left), max(1, bottom - top)), Image.Resampling.LANCZOS)
    shadow_layer = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, opacity))
    shadow_layer.putalpha(alpha.point(lambda a: opacity if a > 16 else 0))
    if blur:
        shadow_alpha = shadow_layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur))
        shadow_layer.putalpha(shadow_alpha)
    silhouette.alpha_composite(shadow_layer, (left + offset[0], top + offset[1]))
    return Image.alpha_composite(canvas, silhouette)


def place_subject(
    canvas: Image.Image,
    cutout: Image.Image,
    scale: float = 1.0,
    position: Tuple[float, float] = (0.5, 0.5),
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """Fit the cutout into the canvas at scale/position; returns (image, subject_box)."""
    if not 0.05 <= scale <= 4.0:
        raise ValueError("Subject scale must be between 0.05 and 4.0.")
    if not (0.0 <= position[0] <= 1.0 and 0.0 <= position[1] <= 1.0):
        raise ValueError("Subject position must be normalized 0..1 coordinates.")
    box_w = canvas.width * scale
    box_h = canvas.height * scale
    ratio = min(box_w / cutout.width, box_h / cutout.height)
    new_w = max(1, round(cutout.width * ratio))
    new_h = max(1, round(cutout.height * ratio))
    subject = cutout.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = round(position[0] * canvas.width - new_w / 2)
    top = round(position[1] * canvas.height - new_h / 2)
    result = canvas.copy()
    # Clip to the overlap region so off-canvas placement never raises.
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(canvas.width, left + new_w), min(canvas.height, top + new_h)
    if x1 > x0 and y1 > y0:
        visible = subject.crop((x0 - left, y0 - top, x1 - left, y1 - top))
        result.alpha_composite(visible, (x0, y0))
    return result, (left, top, left + new_w, top + new_h)


def compose_advanced(
    cutout_path: str,
    output_path: str,
    background: str = "transparent",
    gradient: Tuple[str, str] | None = None,
    gradient_direction: str = "vertical",
    canvas_size: Tuple[int, int] | None = None,
    scale: float = 1.0,
    position: Tuple[float, float] = (0.5, 0.5),
    feather: float = 0.0,
    erode: int = 0,
    shadow: bool = False,
    shadow_opacity: int = 140,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> str:
    """Full advanced composition: background → shadow → subject → export.

    Background selection preserves the existing contract:
    gradient tuple > image file path > "transparent" > solid/named/HEX color.
    """
    cutout = Image.open(cutout_path).convert("RGBA")
    size = canvas_size or cutout.size
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError("Canvas size must be positive.")

    if gradient is not None:
        canvas = make_gradient_background(size, gradient[0], gradient[1], gradient_direction)
        keep_alpha = False
    elif os.path.isfile(background):
        bg = Image.open(background).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        canvas = bg
        keep_alpha = False
    elif background == "transparent":
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        keep_alpha = True
    else:
        rgba = parse_color_to_rgba(background)
        canvas = Image.new("RGBA", size, rgba)
        keep_alpha = rgba[3] < 255

    cutout = refine_edges(cutout, feather=feather, erode=erode)
    cutout = adjust_foreground(cutout, brightness=brightness, contrast=contrast, saturation=saturation)

    placed, subject_box = place_subject(canvas, cutout, scale=scale, position=position)
    if shadow:
        placed = add_subject_shadow(canvas, cutout, subject_box, opacity=shadow_opacity)
        placed, _ = place_subject(placed, cutout, scale=scale, position=position)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if keep_alpha:
        placed.save(output_path, format="PNG")
    else:
        placed.convert("RGB").save(output_path, format="PNG")
    return output_path


def crop_to_preset(image_path: str, preset: str, output_path: str) -> str:
    """Centre-crop an image to a named aspect-ratio preset."""
    if preset not in CROP_PRESETS:
        raise ValueError(f"Unknown crop preset: {preset}. Available: {', '.join(CROP_PRESETS)}")
    ratio_w, ratio_h = CROP_PRESETS[preset]
    image = Image.open(image_path).convert("RGBA")
    target_ratio = ratio_w / ratio_h
    current_ratio = image.width / image.height
    if current_ratio > target_ratio:
        new_w = round(image.height * target_ratio)
        left = (image.width - new_w) // 2
        cropped = image.crop((left, 0, left + new_w, image.height))
    else:
        new_h = round(image.width / target_ratio)
        top = (image.height - new_h) // 2
        cropped = image.crop((0, top, image.width, top + new_h))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cropped.save(output_path, format="PNG")
    return output_path


__all__ = [
    "BACKGROUND_COLOR_PRESETS",
    "GRADIENT_PRESETS",
    "GRADIENT_DIRECTIONS",
    "SOCIAL_IMAGE_PRESETS",
    "CROP_PRESETS",
    "make_gradient_background",
    "refine_edges",
    "adjust_foreground",
    "add_subject_shadow",
    "place_subject",
    "compose_advanced",
    "crop_to_preset",
]
