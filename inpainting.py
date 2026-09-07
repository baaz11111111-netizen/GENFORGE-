import os
import cv2
import numpy as np
from typing import Union, Optional


def run_inpaint(
    image_input: Union[str, np.ndarray],
    mask_input: Union[str, np.ndarray],
    output_path: Optional[str] = None,
    inpaint_radius: int = 3,
    method: str = "telea",
) -> np.ndarray:
    """
    Executes OpenCV inpainting safely by ensuring exact height/width and
    channel match between base image and mask before running C++ logic.
    """
    # 1. Load Base Image
    if isinstance(image_input, str):
        if not os.path.exists(image_input):
            raise FileNotFoundError(f"Base image not found: {image_input}")
        image = cv2.imread(image_input, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Unable to decode image at: {image_input}")
    else:
        image = image_input.copy()

    # Drop alpha channel from base image if 4-channel BGRA
    if len(image.shape) == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    img_h, img_w = image.shape[:2]

    # 2. Load Mask
    if isinstance(mask_input, str):
        if not os.path.exists(mask_input):
            raise FileNotFoundError(f"Mask file not found: {mask_input}")
        mask = cv2.imread(mask_input, cv2.IMREAD_UNCHANGED)
        if mask is None:
            raise ValueError(f"Unable to decode mask at: {mask_input}")
    else:
        mask = mask_input.copy()

    # 3. Convert Mask to Single-Channel Grayscale
    if len(mask.shape) == 3:
        if mask.shape[2] == 4:
            mask = mask[:, :, 3]  # Extract Alpha channel if PNG
        else:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

    # 4. A mask for another image is almost always an upstream bug.
    mask_h, mask_w = mask.shape[:2]
    if (mask_w, mask_h) != (img_w, img_h):
        raise ValueError(
            f"Mask dimensions ({mask_w}x{mask_h}) must match image dimensions ({img_w}x{img_h})."
        )

    # 5. Ensure uint8 data type and binarize
    if mask.dtype != np.uint8:
        mask = (mask * 255).astype(np.uint8) if mask.max() <= 1.0 else mask.astype(np.uint8)
    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

    # 6. Execute C++ Inpainting Core
    algo_flag = cv2.INPAINT_TELEA if method.lower() == "telea" else cv2.INPAINT_NS
    inpainted = cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=algo_flag)

    # 7. Save output if path is specified
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        cv2.imwrite(output_path, inpainted)

    return inpainted