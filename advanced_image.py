import os
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

# ---------------------------------------------------------
# A. FACE-AWARE SMART CROPPING
# ---------------------------------------------------------
def smart_face_crop(image_path: str, output_path: str, target_ratio: str = "9:16") -> str:
    """Crops the image around detected human faces rather than blind center cropping."""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Unable to read image file.")
        
    h, w, _ = img.shape
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Load Haar Cascade for face detection with fallback
    center_x, center_y = w // 2, h // 2
    try:
        if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data'):
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            if len(faces) > 0:
                # Calculate bounding box centroid of the primary face
                fx, fy, fw, fh = faces[0]
                center_x = fx + fw // 2
                center_y = fy + fh // 2
    except Exception as e:
        # Fallback to image center if face detection unavailable or fails
        print(f"[Warning] Face detection failed ({e}); using image center")

    # Calculate crop dimensions based on aspect ratio
    ratio_w, ratio_h = map(float, target_ratio.split(":"))
    
    if (w / h) > (ratio_w / ratio_h):
        crop_h = h
        crop_w = int(h * (ratio_w / ratio_h))
    else:
        crop_w = w
        crop_h = int(w * (ratio_h / ratio_w))

    # Keep crop window inside image boundaries
    left = max(0, min(center_x - crop_w // 2, w - crop_w))
    top = max(0, min(center_y - crop_h // 2, h - crop_h))

    cropped = img[top:top+crop_h, left:left+crop_w]
    if not cv2.imwrite(output_path, cropped):
        raise RuntimeError(f"cv2.imwrite failed to write smart-cropped image: {output_path}")
    return output_path

# ---------------------------------------------------------
# B. CINEMATIC COLOR LUT GRADIENT
# ---------------------------------------------------------
def apply_cinematic_color_grading(image_path: str, output_path: str, preset: str = "teal_orange") -> str:
    """Applies high-grade color matrix adjustments simulating 3D cinematic LUTs."""
    img = Image.open(image_path).convert("RGB")
    
    if preset == "teal_orange":
        r, g, b = img.split()
        r = ImageEnhance.Contrast(r).enhance(1.2)
        b = ImageEnhance.Brightness(b).enhance(1.15)
        img = Image.merge("RGB", (r, g, b))
        img = ImageEnhance.Color(img).enhance(1.3)
    elif preset == "vintage_film":
        r, g, b = img.split()
        r = ImageEnhance.Brightness(r).enhance(1.1)
        b = ImageEnhance.Contrast(b).enhance(0.85)
        img = Image.merge("RGB", (r, g, b))
        img = ImageEnhance.Contrast(img).enhance(0.95)
    elif preset == "cyberpunk":
        r, g, b = img.split()
        r = ImageEnhance.Brightness(r).enhance(1.2)
        g = ImageEnhance.Contrast(g).enhance(0.8)
        b = ImageEnhance.Brightness(b).enhance(1.3)
        img = Image.merge("RGB", (r, g, b))
        img = ImageEnhance.Color(img).enhance(1.5)

    img.save(output_path, quality=95)
    return output_path

# ---------------------------------------------------------
# C. OPENCV INPAINTING (OBJECT REMOVAL)
# ---------------------------------------------------------
def inpaint_mask_area(image_path: str, mask_path: str, output_path: str) -> str:
    """Removes unwanted objects from an image using an inpainting binary mask."""
    img = cv2.imread(image_path)
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    
    if img is None or mask is None:
        raise ValueError("Image or mask path invalid.")

    # Apply Navier-Stokes based inpainting
    restored = cv2.inpaint(img, mask, inpaintRadius=3, flags=cv2.INPAINT_NS)
    if not cv2.imwrite(output_path, restored):
        raise RuntimeError(f"cv2.imwrite failed to write inpainted image: {output_path}")
    return output_path