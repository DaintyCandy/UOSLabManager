"""Pure CompactConnect-style processing for CTvideo preview frames.

The controls represented here belong to CompactConnect's *Video Display*
dialog.  They modify the pixels shown by this application; they do not issue
UVC, DirectShow, Kernel Streaming, or serial commands.  Hardware-backed values
such as anti-flicker and vendor Video Gain deliberately do not belong to this
profile model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any

import numpy as np


VIDEO_DISPLAY_PROFILE_KEY = "video_display"
_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{6})$")
_REFERENCE_BACKGROUND_DIAMETER = 480


def _number(name: str, value: object, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be in range {minimum:g}..{maximum:g}.")
    return result


def _integer(name: str, value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be an integer.")
    if not math.isfinite(float(value)) or int(value) != value:
        raise ValueError(f"{name} must be an integer.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be in range {minimum}..{maximum}.")
    return result


def _boolean(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean.")
    return value


def _color(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a #RRGGBB color string.")
    match = _COLOR_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{name} must be a #RRGGBB color string.")
    return f"#{match.group(1).upper()}"


@dataclass(frozen=True, slots=True)
class CompactConnectVideoDisplaySettings:
    """Validated, immutable state of CompactConnect's Video Display dialog."""

    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    brightness: float = 1.0
    rotation_deg: int = 0
    black_and_white: bool = False
    mirror_x: bool = True
    mirror_y: bool = False
    target_circle_style: str = "solid"
    target_circle_width: int = 5
    target_circle_color: str = "#FF0000"
    background_color: str = "#404040"
    background_circle_color: str = "#000000"
    background_circle_diameter: int = _REFERENCE_BACKGROUND_DIAMETER

    def __post_init__(self) -> None:
        for name in ("red_gain", "green_gain", "blue_gain", "brightness"):
            object.__setattr__(
                self, name, _number(name, getattr(self, name), 0.0, 10.0)
            )
        object.__setattr__(
            self,
            "rotation_deg",
            _integer("rotation_deg", self.rotation_deg, 0, 359),
        )
        for name in ("black_and_white", "mirror_x", "mirror_y"):
            object.__setattr__(self, name, _boolean(name, getattr(self, name)))
        if not isinstance(self.target_circle_style, str):
            raise TypeError("target_circle_style must be 'solid' or 'dotted'.")
        style = self.target_circle_style.strip().casefold()
        if style not in {"solid", "dotted"}:
            raise ValueError("target_circle_style must be 'solid' or 'dotted'.")
        object.__setattr__(self, "target_circle_style", style)
        object.__setattr__(
            self,
            "target_circle_width",
            _integer("target_circle_width", self.target_circle_width, 0, 25),
        )
        for name in (
            "target_circle_color",
            "background_color",
            "background_circle_color",
        ):
            object.__setattr__(self, name, _color(name, getattr(self, name)))
        object.__setattr__(
            self,
            "background_circle_diameter",
            _integer(
                "background_circle_diameter",
                self.background_circle_diameter,
                100,
                1200,
            ),
        )

    @classmethod
    def from_dict(
        cls, values: Mapping[str, object] | None = None
    ) -> "CompactConnectVideoDisplaySettings":
        """Validate a direct settings mapping and fill omitted keys by default."""

        if values is None:
            return cls()
        if not isinstance(values, Mapping):
            raise TypeError("Video display settings must be a mapping.")
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Unknown video display setting(s): " + ", ".join(unknown)
            )
        return cls(**dict(values))

    from_mapping = from_dict

    @classmethod
    def from_profile(
        cls, profile: Mapping[str, object] | None
    ) -> "CompactConnectVideoDisplaySettings":
        """Read either a direct mapping or a ``video_display`` profile section."""

        if profile is None:
            return cls()
        if not isinstance(profile, Mapping):
            raise TypeError("Video display profile must be a mapping.")
        if VIDEO_DISPLAY_PROFILE_KEY in profile:
            section = profile[VIDEO_DISPLAY_PROFILE_KEY]
            if not isinstance(section, Mapping):
                raise TypeError("The video_display profile section must be a mapping.")
            return cls.from_dict(section)
        return cls.from_dict(profile)

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-safe settings mapping."""

        return {item.name: getattr(self, item.name) for item in fields(self)}

    def to_profile(self) -> dict[str, dict[str, object]]:
        """Return a canonical nested profile section."""

        return {VIDEO_DISPLAY_PROFILE_KEY: self.to_dict()}

    def with_updates(self, **changes: object) -> "CompactConnectVideoDisplaySettings":
        """Return a validated copy with the supplied values replaced."""

        unknown = sorted(set(changes) - {item.name for item in fields(self)})
        if unknown:
            raise ValueError(
                "Unknown video display setting(s): " + ", ".join(unknown)
            )
        return replace(self, **changes)


def canonical_video_display_profile(
    profile: Mapping[str, object] | None,
) -> dict[str, dict[str, object]]:
    """Validate and normalize a profile into its canonical nested form."""

    return CompactConnectVideoDisplaySettings.from_profile(profile).to_profile()


def _bgr(color: str) -> tuple[int, int, int]:
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return blue, green, red


def _center_zoom(frame: np.ndarray, diameter: int, cv2_module: Any) -> np.ndarray:
    """Apply cpp_ds's centered ``diameter + 20`` source-window zoom."""

    height, width = frame.shape[:2]
    shortest = min(height, width)
    if diameter >= shortest - 20:
        return frame.copy()

    crop_size = min(shortest, diameter + 20)
    left = max(0, (width - crop_size) // 2)
    top = max(0, (height - crop_size) // 2)
    right = min(width, left + crop_size)
    bottom = min(height, top + crop_size)
    crop = np.ascontiguousarray(frame[top:bottom, left:right])
    return cv2_module.resize(crop, (width, height))


def _rotate(
    frame: np.ndarray,
    angle: int,
    background_bgr: tuple[int, int, int],
    cv2_module: Any,
) -> np.ndarray:
    if angle == 0:
        return frame.copy()
    height, width = frame.shape[:2]
    center = ((width - 1) / 2.0, (height - 1) / 2.0)
    matrix = cv2_module.getRotationMatrix2D(center, float(angle), 1.0)
    kwargs: dict[str, object] = {
        "borderMode": getattr(cv2_module, "BORDER_CONSTANT", 0),
        "borderValue": background_bgr,
    }
    interpolation = getattr(cv2_module, "INTER_LINEAR", None)
    if interpolation is not None:
        kwargs["flags"] = interpolation
    return cv2_module.warpAffine(frame, matrix, (width, height), **kwargs)


def _draw_dotted_circle(
    frame: np.ndarray,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    width: int,
    cv2_module: Any,
) -> None:
    if radius <= 0:
        return
    line_type = getattr(cv2_module, "LINE_AA", 8)
    dot_radius = max(1, (width + 1) // 2)
    circumference = 2.0 * math.pi * radius
    dot_count = max(12, int(circumference / max(4, width * 3)))
    for index in range(dot_count):
        angle = 2.0 * math.pi * index / dot_count
        point = (
            int(round(center[0] + radius * math.cos(angle))),
            int(round(center[1] + radius * math.sin(angle))),
        )
        cv2_module.circle(frame, point, dot_radius, color, -1, line_type)


def _apply_circular_background(
    frame: np.ndarray,
    diameter: int,
    color: tuple[int, int, int],
    cv2_module: Any,
) -> None:
    """Fill the area outside CompactConnect's circular video aperture."""

    height, width = frame.shape[:2]
    shortest = min(height, width)
    if diameter < shortest - 20:
        displayed_diameter = diameter * shortest / float(diameter + 20)
    else:
        displayed_diameter = float(diameter)
    radius = min(displayed_diameter / 2.0, shortest / 2.0)
    center_x = width // 2
    center_y = height // 2
    yy, xx = np.ogrid[:height, :width]
    outside = (
        (xx - center_x) * (xx - center_x)
        + (yy - center_y) * (yy - center_y)
    ) > radius * radius
    frame[outside] = color
    cv2_module.circle(
        frame,
        (center_x, center_y),
        max(1, int(round(radius))),
        (0, 0, 0),
        3,
        getattr(cv2_module, "LINE_AA", 8),
    )


def process_frame(
    frame: np.ndarray,
    settings: CompactConnectVideoDisplaySettings | Mapping[str, object],
    cv2_module: Any,
) -> np.ndarray:
    """Return a processed BGR frame without mutating ``frame`` or hardware.

    The target-circle diameter is not exposed by CompactConnect's Adjust Video
    dialog; the real application derives it from pyrometer optics and distance.
    Until that geometry is available to this application, a centered fallback
    diameter of one sixth of the output's shorter dimension is used.
    """

    if not isinstance(settings, CompactConnectVideoDisplaySettings):
        settings = CompactConnectVideoDisplaySettings.from_dict(settings)
    source = np.asarray(frame)
    if source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("frame must be a non-empty H x W x 3 BGR array.")
    if source.shape[0] <= 0 or source.shape[1] <= 0:
        raise ValueError("frame must be a non-empty H x W x 3 BGR array.")
    if not np.issubdtype(source.dtype, np.number):
        raise TypeError("frame must contain numeric BGR values.")

    working = source.astype(np.float32, copy=True)
    channel_scale = np.array(
        [settings.blue_gain, settings.green_gain, settings.red_gain],
        dtype=np.float32,
    ) * settings.brightness
    working *= channel_scale
    result = np.clip(working, 0.0, 255.0).astype(np.uint8)

    if settings.black_and_white:
        gray = np.rint(
            result[:, :, 0].astype(np.float32) * 0.114
            + result[:, :, 1].astype(np.float32) * 0.587
            + result[:, :, 2].astype(np.float32) * 0.299
        ).astype(np.uint8)
        result = np.repeat(gray[:, :, np.newaxis], 3, axis=2)

    if settings.mirror_x:
        result = result[:, ::-1, :]
    if settings.mirror_y:
        result = result[::-1, :, :]
    result = np.ascontiguousarray(result)

    result = _rotate(
        result,
        settings.rotation_deg,
        _bgr(settings.background_color),
        cv2_module,
    )
    result = _center_zoom(
        result, settings.background_circle_diameter, cv2_module
    )
    result = np.ascontiguousarray(result)

    height, width = result.shape[:2]
    shortest = min(height, width)
    center = (width // 2, height // 2)
    line_type = getattr(cv2_module, "LINE_AA", 8)

    _apply_circular_background(
        result,
        settings.background_circle_diameter,
        _bgr(settings.background_circle_color),
        cv2_module,
    )

    target_diameter = max(2, shortest // 6)
    target_radius = max(1, target_diameter // 2)
    target_color = _bgr(settings.target_circle_color)
    if settings.target_circle_style == "dotted":
        _draw_dotted_circle(
            result,
            center,
            target_radius,
            target_color,
            settings.target_circle_width,
            cv2_module,
        )
    else:
        cv2_module.circle(
            result,
            center,
            target_radius,
            target_color,
            max(1, settings.target_circle_width),
            line_type,
        )
    return result


__all__ = [
    "VIDEO_DISPLAY_PROFILE_KEY",
    "CompactConnectVideoDisplaySettings",
    "canonical_video_display_profile",
    "process_frame",
]
