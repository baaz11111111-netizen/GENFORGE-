"""MCP adapter around GENFORGE's canonical media services.

MCP owns transport and tool registration only. Media behavior remains in the
domain modules so UI, agents, and MCP callers execute the same operations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, TypeVar

from advanced_editing import (
    auto_caption_video as _auto_caption_video,
    extract_highlights as _extract_highlights,
    remove_silence as _remove_silence,
    resize_video_aspect as _resize_video_aspect,
    trim_clip as _trim_clip,
)
from inpainting import run_inpaint

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment,misc]

T = TypeVar("T", bound=Callable[..., Any])


class _NoopMCP:
    def tool(self) -> Callable[[T], T]:
        def decorator(function: T) -> T:
            return function

        return decorator

    def run(self) -> None:
        raise RuntimeError("FastMCP is not installed. Install the 'fastmcp' dependency.")


mcp = FastMCP("GENFORGE Media Server") if FastMCP is not None else _NoopMCP()


def _input(path: str, label: str = "input") -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{label} path must be non-empty")
    resolved = str(Path(path).expanduser().resolve())
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"{label} file not found: {resolved}")
    return resolved


def _output(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("output_path must be non-empty")
    resolved = str(Path(path).expanduser().resolve())
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ValueError(f"output_path is not a file: {resolved}")
    os.makedirs(os.path.dirname(resolved) or os.curdir, exist_ok=True)
    return resolved


@mcp.tool()
def inpaint_image_tool(image_path: str, mask_path: str, output_path: str = "") -> str:
    image = _input(image_path, "image")
    mask = _input(mask_path, "mask")
    destination = _output(output_path or os.path.join("outputs", f"inpaint_{Path(image).stem}.png"))
    run_inpaint(image, mask, destination)
    return destination


@mcp.tool()
def trim_clip(input_path: str, output_path: str, start_time: float, end_time: float) -> str:
    return _trim_clip(_input(input_path), _output(output_path), start_time, end_time)


@mcp.tool()
def remove_silence(input_path: str, output_path: str, noise_threshold_db: int = -30, min_silence_duration: float = 0.5) -> str:
    return _remove_silence(_input(input_path), _output(output_path), noise_threshold_db, min_silence_duration)


@mcp.tool()
def auto_caption_video(input_path: str, output_path: str) -> str:
    return _auto_caption_video(_input(input_path), _output(output_path))


@mcp.tool()
def extract_highlights(input_path: str, output_path: str, max_duration: float = 15.0) -> str:
    return _extract_highlights(_input(input_path), _output(output_path), max_duration)


@mcp.tool()
def resize_video_aspect(input_path: str, output_path: str, target_ratio: str = "9:16") -> str:
    return _resize_video_aspect(_input(input_path), _output(output_path), target_ratio)


if __name__ == "__main__":
    mcp.run()
