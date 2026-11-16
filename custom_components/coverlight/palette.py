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
from typing import NamedTuple

from PIL import Image

# A color is (hue, saturation), both 0..1. Brightness is applied separately per room.
HS = tuple[float, float]


class Swatch(NamedTuple):
    """One palette color, plus how bright it is and how much of the cover it covers."""

    hue: float
    saturation: float
    level: float = 1.0  # brightness relative to the palette's brightest color, 0..1
    weight: float = 1.0  # share of the cover; a palette's weights sum to 1


class Target(NamedTuple):
    """What one light should show: a color and a brightness factor (0..1) for the room slider."""

    hue: float
    saturation: float
    brightness: float


WARM_WHITE = Swatch(*colorsys.rgb_to_hsv(1.0, 0.74, 0.45)[:2])

_BINS = 36  # 10° per bin
_SIDE = 64

# Darker palette colors play at this fraction of the room brightness, up to 100 % for the
# brightest. Any lower and a deep color reads as "the light is half off".
LEVEL_FLOOR = 0.6
# At 100 % motion, lights breathe down by up to this much. Only ever dims, so the
# brightness slider stays the ceiling.
BREATH_DEPTH = 0.15
# Deliberately not a multiple of the color drift period, so brightness and color don't move
# in lockstep.
BREATH_PERIOD = 19.0  # seconds


def extract_palette(image_data: bytes, max_colors: int = 5) -> list[Swatch]:
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

    # (hue, saturation, value, score) until normalised below.
    picks: list[tuple[float, float, float, float]] = []
    blocked: set[int] = set()
    strongest: float | None = None
    while len(picks) < max_colors:
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
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        picks.append((h, min(1.0, s * 1.2 + 0.1), v, score))
        # Keep picks at least ~40° apart so the palette has real variety.
        blocked.update((best + offset) % _BINS for offset in range(-3, 4))

    # Mostly black/white/grey artwork: let a warm white carry it.
    if len(picks) < 2 and bright_neutral / total > 0.15:
        picks.append((WARM_WHITE.hue, WARM_WHITE.saturation, 1.0, float(bright_neutral)))
    if not picks:
        return [WARM_WHITE]

    brightest = max(v for _, _, v, _ in picks) or 1.0
    score_sum = sum(score for *_, score in picks)
    return [Swatch(h, s, v / brightest, score / score_sum) for h, s, v, score in picks]


def assign_lights(palette: list[Swatch], count: int) -> list[int]:
    """Palette index for each of `count` lights, in room order.

    With at least as many colors as lights, lights take the strongest colors in order. With more
    lights than colors, every color keeps one light and the extras go to the colors that cover
    most of the artwork, spread out through the room rather than bunched together.
    """
    if count <= 0:
        return []
    colors = len(palette)
    if count <= colors:
        return list(range(count))

    # One light each, then hand out the rest by largest remainder of each color's fair share.
    shares = [swatch.weight * count for swatch in palette]
    lights = [1] * colors
    spare = count - colors
    while spare:
        best = max(range(colors), key=lambda i: shares[i] - lights[i])
        lights[best] += 1
        spare -= 1

    # Smooth weighted round-robin: deterministic, and interleaves the colors evenly.
    order: list[int] = []
    current = [0] * colors
    for _ in range(count):
        for i in range(colors):
            current[i] += lights[i]
        best = max(range(colors), key=lambda i: current[i])
        current[best] -= count
        order.append(best)
    return order


def mix(a: HS, b: HS, amount: float) -> HS:
    """Blend two colors along the shorter way round the hue wheel.

    Mixing in hue space keeps the in-between colors vivid; mixing RGB would wash
    red→cyan out to grey, which a bulb renders as plain white.
    """
    delta = (b[0] - a[0] + 0.5) % 1.0 - 0.5
    return ((a[0] + delta * amount) % 1.0, a[1] + (b[1] - a[1]) * amount)


def light_target(
    palette: list[Swatch], slot: int, rank: int, time: float, motion: float, period: float
) -> Target:
    """Color and brightness for the light at position `rank`, showing palette color `slot`.

    The light drifts from its color toward the next palette color and back, and breathes a
    little dimmer and brighter. Each light is phase-shifted so the room never moves in
    lockstep. `motion` (0..1) scales both; at 0 the light holds its palette color.
    """
    base = palette[slot % len(palette)]
    color: HS = (base.hue, base.saturation)
    level = base.level
    breath = 1.0
    if motion > 0:
        if len(palette) > 1:
            following = palette[(slot + 1) % len(palette)]
            phase = time / period + rank * 0.29
            amount = (0.5 - 0.5 * math.cos(2 * math.pi * phase)) * motion
            color = mix(color, (following.hue, following.saturation), amount)
            level += (following.level - level) * amount
        breath_phase = time / BREATH_PERIOD + rank * 0.37
        breath -= BREATH_DEPTH * motion * (0.5 - 0.5 * math.cos(2 * math.pi * breath_phase))
    return Target(*color, (LEVEL_FLOOR + (1 - LEVEL_FLOOR) * level) * breath)
