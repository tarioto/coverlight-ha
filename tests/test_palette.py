import io

from PIL import Image

from custom_components.coverlight.palette import (
    BREATH_DEPTH,
    LEVEL_FLOOR,
    WARM_WHITE,
    Swatch,
    assign_lights,
    extract_palette,
    light_target,
    mix,
)


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
    hues = [swatch.hue for swatch in palette]
    assert len(palette) == 2
    assert any(_hue_distance(h, 0.0) < 0.03 for h in hues)  # red
    assert any(_hue_distance(h, 0.66) < 0.03 for h in hues)  # blue
    assert all(swatch.saturation > 0.8 for swatch in palette)


def test_small_accent_survives():
    image = Image.new("RGB", (300, 300), (15, 15, 15))
    image.paste((255, 0, 200), (0, 0, 60, 60))  # 4% magenta logo on black
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    palette = extract_palette(buffer.getvalue())
    assert _hue_distance(palette[0].hue, 0.87) < 0.03


def test_swatches_carry_weight_and_relative_brightness():
    # Three quarters bright red, one quarter dark blue.
    palette = extract_palette(_jpeg((230, 20, 20), (230, 20, 20), (230, 20, 20), (20, 30, 110)))
    red, blue = palette
    assert _hue_distance(red.hue, 0.0) < 0.03
    assert abs(sum(swatch.weight for swatch in palette) - 1) < 1e-9
    assert red.weight > 0.8  # vivid and three times the area
    assert red.level == 1.0
    assert 0.3 < blue.level < 0.6  # about half as bright as the red


def test_greyscale_cover_falls_back_to_warm_white():
    assert extract_palette(_jpeg((240, 240, 240), (10, 10, 10))) == [WARM_WHITE]


def test_garbage_bytes_fall_back_to_warm_white():
    assert extract_palette(b"not an image") == [WARM_WHITE]


def test_mix_goes_the_short_way_round():
    h, s = mix((0.95, 1.0), (0.05, 0.5), 0.5)
    assert _hue_distance(h, 0.0) < 1e-9
    assert abs(s - 0.75) < 1e-9


def test_fewer_lights_than_colors_take_the_strongest_in_order():
    palette = [Swatch(0.0, 1.0, 1.0, 0.5), Swatch(0.3, 1.0, 1.0, 0.3), Swatch(0.6, 1.0, 1.0, 0.2)]
    assert assign_lights(palette, 2) == [0, 1]
    assert assign_lights(palette, 0) == []
    assert assign_lights([WARM_WHITE], 3) == [0, 0, 0]


def test_extra_lights_go_to_dominant_colors_spread_out():
    palette = [Swatch(0.0, 1.0, 1.0, 0.7), Swatch(0.3, 1.0, 1.0, 0.2), Swatch(0.6, 1.0, 1.0, 0.1)]
    slots = assign_lights(palette, 5)
    assert sorted(slots) == [0, 0, 0, 1, 2]  # every color keeps a light; red gets the rest
    assert slots == [0, 1, 0, 2, 0]  # and red is spread through the room, not bunched


def test_holds_still_without_motion():
    palette = [Swatch(0.1, 1.0), Swatch(0.6, 1.0)]
    assert light_target(palette, 0, 0, 123.0, 0.0, 24) == (0.1, 1.0, 1.0)
    assert light_target(palette, 1, 3, 0.0, 0.0, 24) == (0.6, 1.0, 1.0)
    # A darker palette color plays dimmer, but never below the floor.
    dark = [Swatch(0.1, 1.0, level=0.0)]
    assert light_target(dark, 0, 0, 5.0, 0.0, 24).brightness == LEVEL_FLOOR


def test_drift_moves_partway_toward_next_color():
    palette = [Swatch(0.0, 1.0), Swatch(0.2, 1.0)]
    hues = {round(light_target(palette, 0, 0, t, 0.5, 24).hue, 4) for t in range(0, 24, 2)}
    assert len(hues) > 3
    assert min(hues) >= 0.0 and max(hues) <= 0.1 + 1e-9  # at most halfway at 50% motion


def test_single_color_breathes_but_never_brightens():
    palette = [Swatch(0.3, 0.9)]
    targets = [light_target(palette, 0, 0, t / 2, 1.0, 24) for t in range(40)]
    assert {(t.hue, t.saturation) for t in targets} == {(0.3, 0.9)}
    levels = [t.brightness for t in targets]
    assert max(levels) <= 1.0
    assert min(levels) < 1 - BREATH_DEPTH * 0.9  # dips nearly the full depth at 100% motion
