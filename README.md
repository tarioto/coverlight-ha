# Coverlight for Home Assistant

Room lights that take their colors from the album art of whatever the room's speaker is playing,
and drift slowly between them. It's the Home Assistant version of the Coverlight Mac app, so it works in
any room without a Mac.

It uses the speaker and light integrations you already have (Sonos and Philips Hue, but any
`media_player` with artwork and any color `light` works).

## Install

**With HACS (recommended):**
1. **HACS → ⋮ → Custom repositories**, add `https://github.com/tarioto/coverlight-ha`, type **Integration**.
2. Search HACS for **Coverlight**, **Download**, then restart Home Assistant.

HACS shows new releases as updates.

**By hand:** copy `custom_components/coverlight` into the `custom_components` folder of your Home Assistant
config (for example over the Samba share add-on) and restart.

## Add a room

**Settings → Devices & services → Add integration → Coverlight**, then pick:

- **Speaker**: the room's Sonos (`media_player.kitchen`, …)
- **Lights**: the color lights to follow it. Neighbouring lights in the list get neighbouring palette colors.
- **Restore lights when sync turns off**: on by default.

Repeat for each room. Change a room later with **Configure** on its entry.

Each room becomes a device with:

| Entity | What it does |
| --- | --- |
| `switch.coverlight_<room>_sync` | Start/stop following the speaker. Survives restarts. |
| `number.coverlight_<room>_brightness` | Maximum light brightness, 1–100 %. |
| `number.coverlight_<room>_motion` | How far each light drifts toward its neighbour's color, and how deeply it breathes. 0 % holds still. |

## How it behaves

- **New track:** a palette of up to 5 colors is pulled from the cover art, and the lights crossfade to it over 2 s,
  one after another in list order so the new colors sweep through the room.
  The palette favors vivid hues; mostly black-and-white covers fall back to warm white.
- **Which light gets which color:** every palette color gets at least one light. If there are more lights than
  colors, the colors that fill most of the cover get the extra lights, spread through the room.
- **Brightness:** darker colors on the cover play dimmer (down to 60 % of the Brightness slider), so the room
  has some depth instead of every light at the same level.
- **While playing:** each light slowly drifts toward the next palette color (24 s cycle, phase-shifted
  per light) and gently breathes a little dimmer and back (19 s cycle, up to 15 % at full Motion).
  Each light gets a command every 3 s or more, using a matching transition so the bridge smooths it. That keeps several rooms well under the Hue bridge's rate limit.
- **Paused:** colors hold.
- **A light switched off by hand** stays off until sync is turned off and on again.
- **Sync off:** lights return to how they were when sync started.

## Automation idea

```yaml
alias: Kitchen glow when music starts in the evening
triggers:
  - trigger: state
    entity_id: media_player.kitchen
    to: playing
conditions:
  - condition: sun
    after: sunset
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.coverlight_kitchen_sync
```

## Development

```sh
uv venv -p 3.13 .venv && uv pip install -p .venv pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```
