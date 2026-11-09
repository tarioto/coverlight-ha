"""Constants for Coverlight."""

DOMAIN = "coverlight"

CONF_MEDIA_PLAYER = "media_player"
CONF_LIGHTS = "lights"
CONF_RESTORE_LIGHTS = "restore_lights"

DEFAULT_BRIGHTNESS = 80  # percent
DEFAULT_MOTION = 50  # percent

# One full drift cycle between neighbouring palette colors.
DRIFT_PERIOD = 24.0  # seconds
# How often each light gets a new target. Every command uses this as its transition, so the
# bridge interpolates in between and the drift looks continuous at a low command rate.
MIN_STEP = 3.0  # seconds
STEP_PER_LIGHT = 0.4  # seconds; keeps big rooms under the Hue bridge's ~10 commands/s
# Crossfade when the track (and so the palette) changes.
TRACK_TRANSITION = 2.0  # seconds
