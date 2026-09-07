import os

import re
import time
import uuid as _uuid_mod
from typing import Literal, Optional, Tuple
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel, Field
from inpainting import run_inpaint  # Integrated safe inpainter
from services.ai_service import generate_json

try:
    from rembg import new_session as _rembg_session, remove as _rembg_remove
    HAS_REMBG = True
except (ImportError, SystemExit, Exception):
    HAS_REMBG = False


class ImageEditPlan(BaseModel):
    remove_background: bool = Field(default=False, description="Set to True to remove image background")
    background_color: str = Field(
        default="transparent",
        description="Background color to apply after removal (e.g., 'transparent', 'white', 'black', 'blue', '#0000FF')"
    )
    grayscale: bool = Field(default=False, description="Set to True to apply grayscale filter")
    brightness: float = Field(default=1.0, description="Brightness multiplier (1.0 = normal, >1.0 brighter, <1.0 darker)")
    contrast: float = Field(default=1.0, description="Contrast multiplier (1.0 = normal, >1.0 higher contrast)")
    blur_radius: float = Field(default=0.0, description="Radius for Gaussian blur (0.0 = no blur)")
    aspect_ratio: Literal["9:16", "1:1", "16:9", "none"] = Field(default="none", description="Aspect ratio crop mode")


def parse_color_to_rgba(color_str: str) -> tuple:
    """Converts a color string name or hex code to an RGBA tuple."""
    color_str = color_str.strip().lower()
    color_map = {
        "white": (255, 255, 255, 255), "black": (0, 0, 0, 255), "blue": (0, 0, 255, 255),
        "red": (255, 0, 0, 255), "green": (0, 255, 0, 255), "yellow": (255, 255, 0, 255),
        "orange": (255, 165, 0, 255), "purple": (128, 0, 128, 255), "pink": (255, 192, 203, 255),
        "gray": (128, 128, 128, 255), "transparent": (0, 0, 0, 0)
    }
    
    if color_str in color_map:
        return color_map[color_str]
    
    if color_str.startswith("#"):
        try:
            return hex_to_rgba(color_str)
        except ValueError:
            pass

    raise ValueError(f"Unsupported color value: {color_str}")


def validate_hex_color(hex_str: str) -> bool:
    """Validates a HEX color string. Accepts #RGB, #RRGGBB, or #RRGGBBAA formats."""
    if not isinstance(hex_str, str):
        return False
    hex_str = hex_str.strip()
    if not hex_str.startswith("#"):
        return False
    hex_val = hex_str.lstrip("#")
    if len(hex_val) == 3:
        hex_val = "".join([c * 2 for c in hex_val])
    if len(hex_val) not in (6, 8):
        return False
    try:
        int(hex_val, 16)
        return True
    except ValueError:
        return False


def hex_to_rgba(hex_str: str) -> Tuple[int, int, int, int]:
    """Converts a validated HEX color string to an RGBA tuple."""
    hex_str = hex_str.strip()
    hex_val = hex_str.lstrip("#")
    if len(hex_val) == 3:
        hex_val = "".join([c * 2 for c in hex_val])
    if len(hex_val) == 6:
        return (int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16), 255)
    if len(hex_val) == 8:
        return (int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16), int(hex_val[6:8], 16))
    raise ValueError(f"Invalid HEX color: {hex_str}")


def remove_image_background(image_path: str, output_path: str) -> str:
    """Removes the background from an image and saves the RGBA cutout.

    Requires rembg. Raises RuntimeError if rembg is unavailable.
    """
    if not HAS_REMBG:
        raise RuntimeError(
            "Background removal requires the 'rembg' package. "
            "Install with: pip install rembg"
        )
    img = Image.open(image_path).convert("RGBA")
    max_dim = 1280
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    session = _rembg_session("u2netp")
    cutout = _rembg_remove(img, session=session)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cutout.save(output_path, format="PNG")
    return output_path


def composite_on_background(
    cutout_path: str,
    background: str,
    output_path: str,
) -> str:
    """Composites an RGBA foreground cutout onto a background.

    Args:
        cutout_path: Path to RGBA PNG with alpha channel (foreground subject).
        background: One of:
            - "transparent" → saves PNG with alpha
            - HEX color string (e.g. "#FF0000") → solid color background
            - Named color (e.g. "white", "black") → solid color background
            - Path to an existing image file → image background
        output_path: Where to save the composited result.

    Returns:
        output_path on success.
    """
    cutout = Image.open(cutout_path).convert("RGBA")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if background == "transparent":
        cutout.save(output_path, format="PNG")
        return output_path

    # Check if background is a file path (image background)
    if os.path.isfile(background):
        bg_img = Image.open(background).convert("RGBA")
        bg_img = bg_img.resize(cutout.size, Image.Resampling.LANCZOS)
        composited = Image.alpha_composite(bg_img, cutout)
        composited.save(output_path, format="PNG")
        return output_path

    # Solid color background
    rgba_color = parse_color_to_rgba(background)
    bg_layer = Image.new("RGBA", cutout.size, rgba_color)
    composited = Image.alpha_composite(bg_layer, cutout)

    # Fully opaque background flattens to RGB (JPEG-compatible).
    # Semi-transparent (#RRGGBBAA with alpha < 255) must stay RGBA so the
    # alpha actually affects the exported pixels.
    if rgba_color[3] == 255:
        composited = composited.convert("RGB")
        composited.save(output_path, format="PNG")
    else:
        composited.save(output_path, format="PNG")

    return output_path


def run_image_agent(
    user_prompt: str,
    image_path: str,
    mask_path: Optional[str] = None,
    output_dir: str = "outputs",
) -> str:
    """Parses natural language image editing prompts and runs PIL, rembg, or inpainting transformations."""
    # 0. Check for inpainting request with mask
    if mask_path and os.path.exists(mask_path):
        print(f"[Image-Agent] Executing safe OpenCV inpainting with mask: {mask_path}")
        unique_id = _uuid_mod.uuid4().hex
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"inpainted_{unique_id}.png")
        return run_inpaint(image_input=image_path, mask_input=mask_path, output_path=out_path)

    print(f"\n[Image-Agent] Processing image: {image_path}")
    img = Image.open(image_path).convert("RGBA")

    unique_id = _uuid_mod.uuid4().hex
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"image_{unique_id}.png")

    system_instruction = (
        "You are an expert AI Image Processing Director. "
        "Analyze the user request and generate structured JSON transformation parameters strictly matching the schema. "
        "Extract any background color requests into background_color."
    )

    plan = ImageEditPlan()

    try:
        parsed_data = generate_json(
            system_instruction + f"\nUser Prompt: '{user_prompt}'",
            response_schema=ImageEditPlan,
        )
        plan = ImageEditPlan.model_validate(parsed_data)
        print(f"[Image-Agent] Parameters extracted: {plan.model_dump()}")
    except Exception:
        # Deterministic parsing below remains the honest offline path.
        pass

    if not plan.remove_background and any(k in user_prompt.lower() for k in ["background", "remove bg", "bg"]):
        plan.remove_background = True
        for color in ["blue", "white", "black", "red", "green", "orange", "yellow"]:
            if color in user_prompt.lower():
                plan.background_color = color
                break

    # Background Removal Pipeline — only when explicitly requested.
    # Do NOT trigger based on background_color alone: the default field value
    # ("transparent") is a safe no-op, but any AI-parsed non-transparent value
    # should not silently remove the background without an explicit request.
    if plan.remove_background:
        try:
            print("[Image-Agent] Running background processing pipeline...")
            from rembg import new_session, remove

            max_dim = 1280
            if max(img.width, img.height) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            session = new_session("u2netp")
            cutout = remove(img, session=session)

            rgba_color = parse_color_to_rgba(plan.background_color)
            if rgba_color[3] > 0:
                background = Image.new("RGBA", cutout.size, rgba_color)
                img = Image.alpha_composite(background, cutout)
            else:
                img = cutout
        except Exception as bg_err:
            raise RuntimeError(f"Background removal failed; no processed image was produced: {bg_err}") from bg_err

    if plan.grayscale:
        if img.mode == "RGBA":
            alpha = img.split()[-1]
            gray = img.convert("L").convert("RGB").convert("RGBA")
            gray.putalpha(alpha)
            img = gray
        else:
            img = img.convert("L").convert("RGB")

    if plan.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(plan.brightness)

    if plan.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(plan.contrast)

    if plan.blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(plan.blur_radius))

    aspect = plan.aspect_ratio.lower()
    w, h = img.size

    if aspect == "9:16" or "shorts" in user_prompt.lower() or "vertical" in user_prompt.lower():
        target_w = int(h * (9 / 16))
        if target_w < w:
            left = (w - target_w) // 2
            img = img.crop((left, 0, left + target_w, h))
    elif aspect == "1:1" or "square" in user_prompt.lower():
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        img = img.crop((left, top, left + min_dim, top + min_dim))
    elif aspect == "16:9" or "landscape" in user_prompt.lower():
        target_h = int(w * (9 / 16))
        if target_h < h:
            top = (h - target_h) // 2
            img = img.crop((0, top, w, top + target_h))

    save_format = "JPEG" if img.mode == "RGB" else "PNG"
    file_ext = ".jpg" if save_format == "JPEG" else ".png"
    
    if not output_path.endswith(file_ext):
        output_path = os.path.splitext(output_path)[0] + file_ext
        
    img.save(output_path, format=save_format)
    return output_path