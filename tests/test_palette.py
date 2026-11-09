import io

from PIL import Image

from custom_components.coverlight.palette import WARM_WHITE, drift_color, extract_palette, mix


def _jpeg(*bands):
    """Vertical bands of solid color, equal widths."""
    image = Image.new("RGB", (300, 300))
    width = 300 // len(bands)
    for i, color in enumerate(bands):
        image.paste(color, (i * width, 0, (i + 1) * width, 300))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def _hue_distance(a, b):
    d = abs(a - b) % 1
    return min(d, 1 - d)


def test_two_color_cover_gives_both_hues():
    palette = extract_palette(_jpeg((230, 20, 20), (20, 40, 230)))
    hues = [h for h, _ in palette]
    assert len(palette) == 2
    assert any(_hue_distance(h, 0.0) < 0.03 for h in hues)  # red
    assert any(_hue_distance(h, 0.66) < 0.03 for h in hues)  # blue
    assert all(s > 0.8 for _, s in palette)


def test_small_accent_survives():
    image = Image.new("RGB", (300, 300), (15, 15, 15))
    image.paste((255, 0, 200), (0, 0, 60, 60))  # 4% magenta logo on black
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    palette = extract_palette(buffer.getvalue())
    assert _hue_distance(palette[0][0], 0.87) < 0.03


def test_greyscale_cover_falls_back_to_warm_white():
    assert extract_palette(_jpeg((240, 240, 240), (10, 10, 10))) == [WARM_WHITE]


def test_garbage_bytes_fall_back_to_warm_white():
    assert extract_palette(b"not an image") == [WARM_WHITE]


def test_mix_goes_the_short_way_round():
    h, s = mix((0.95, 1.0), (0.05, 0.5), 0.5)
    assert _hue_distance(h, 0.0) < 1e-9
    assert abs(s - 0.75) < 1e-9


def test_drift_stays_put_without_motion_or_variety():
    palette = [(0.1, 1.0), (0.6, 1.0)]
    assert drift_color(palette, 0, 123.0, 0.0, 24) == palette[0]
    assert drift_color([(0.3, 0.9)], 4, 123.0, 1.0, 24) == (0.3, 0.9)
    # Lights are assigned palette colors round-robin.
    assert drift_color(palette, 3, 0.0, 0.0, 24) == palette[1]


def test_drift_moves_partway_toward_next_color():
    palette = [(0.0, 1.0), (0.2, 1.0)]
    hues = {round(drift_color(palette, 0, t, 0.5, 24)[0], 4) for t in range(0, 24, 2)}
    assert len(hues) > 3
    assert min(hues) >= 0.0 and max(hues) <= 0.1 + 1e-9  # at most halfway at 50% motion
