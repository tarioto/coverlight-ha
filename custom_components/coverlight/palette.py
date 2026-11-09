"""Light-friendly palettes from album artwork (port of Coverlight's PaletteExtractor.swift).

Lights only show hue and saturation well (dark colors just look "off"), so instead of clustering
raw RGB we build a hue histogram weighted by how vivid each pixel is, then pick its strongest
peaks. That keeps small but striking accents that clustering tends to average away.

Pure Python + Pillow, no Home Assistant imports, so it can be unit tested on its own.
"""

from __future__ import annotations

import colorsys
import io
import math

from PIL import Image

# A color is (hue, saturation), both 0..1. Brightness is applied separately per room.
HS = tuple[float, float]

WARM_WHITE: HS = colorsys.rgb_to_hsv(1.0, 0.74, 0.45)[:2]

_BINS = 36  # 10° per bin
_SIDE = 64


def extract_palette(image_data: bytes, max_colors: int = 5) -> list[HS]:
    """Return up to `max_colors` colors, strongest first."""
    try:
        image = Image.open(io.BytesIO(image_data))
        image.draft("RGB", (128, 128))  # fast JPEG downscale
        image = image.convert("RGBA").resize((_SIDE, _SIDE), Image.Resampling.BILINEAR)
    except (OSError, ValueError):
        return [WARM_WHITE]

    pixels = [(r / 255, g / 255, b / 255) for r, g, b, a in image.getdata() if a > 128]
    if not pixels:
        return [WARM_WHITE]

    weights = [0.0] * _BINS
    sums = [[0.0, 0.0, 0.0] for _ in range(_BINS)]
    bright_neutral = 0
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        vividness = s * v
        if vividness < 0.1:
            if v > 0.45:
                bright_neutral += 1
            continue
        index = min(_BINS - 1, int(h * _BINS))
        weights[index] += vividness
        acc = sums[index]
        acc[0] += r * vividness
        acc[1] += g * vividness
        acc[2] += b * vividness

    def neighborhood(index: int) -> list[int]:
        return [(index - 1) % _BINS, index, (index + 1) % _BINS]

    scores = [sum(weights[n] for n in neighborhood(i)) for i in range(_BINS)]
    total = len(pixels)

    colors: list[HS] = []
    blocked: set[int] = set()
    strongest: float | None = None
    while len(colors) < max_colors:
        candidates = [i for i in range(_BINS) if i not in blocked]
        if not candidates:
            break
        best = max(candidates, key=lambda i: scores[i])
        score = scores[best]
        if score / total <= 0.002 or score <= (strongest or 0) * 0.05:
            break
        strongest = strongest if strongest is not None else score

        bins = neighborhood(best)
        weight = sum(weights[n] for n in bins)
        r, g, b = (sum(sums[n][c] for n in bins) / weight for c in range(3))
        h, s, _ = colorsys.rgb_to_hsv(r, g, b)
        colors.append((h, min(1.0, s * 1.2 + 0.1)))
        # Keep picks at least ~40° apart so the palette has real variety.
        blocked.update((best + offset) % _BINS for offset in range(-3, 4))

    # Mostly black/white/grey artwork: let a warm white carry it.
    if len(colors) < 2 and bright_neutral / total > 0.15:
        colors.append(WARM_WHITE)
    return colors or [WARM_WHITE]


def mix(a: HS, b: HS, amount: float) -> HS:
    """Blend two colors along the shorter way round the hue wheel.

    Mixing in hue space keeps the in-between colors vivid; mixing RGB would wash
    red→cyan out to grey, which a bulb renders as plain white.
    """
    delta = (b[0] - a[0] + 0.5) % 1.0 - 0.5
    return ((a[0] + delta * amount) % 1.0, a[1] + (b[1] - a[1]) * amount)


def drift_color(palette: list[HS], rank: int, time: float, motion: float, period: float) -> HS:
    """Color for the light at position `rank`: its palette color, drifting toward the next one.

    Each light is phase-shifted so the room never moves in lockstep. `motion` (0..1) is how far
    toward the neighbouring color a light travels at the peak of its cycle.
    """
    base = palette[rank % len(palette)]
    if len(palette) < 2 or motion <= 0:
        return base
    following = palette[(rank + 1) % len(palette)]
    phase = time / period + rank * 0.29
    weight = (0.5 - 0.5 * math.cos(2 * math.pi * phase)) * motion
    return mix(base, following, weight)
