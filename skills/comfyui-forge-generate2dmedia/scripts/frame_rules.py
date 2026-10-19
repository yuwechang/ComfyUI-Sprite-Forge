"""Shared source-frame arithmetic for planning and ComfyUI submission (stdlib only)."""
import math


def frame_count(duration, fps, multiple=17, offset=5, minimum=5):
    duration, fps = float(duration), float(fps)
    if not all(math.isfinite(x) and x > 0 for x in (duration, fps)):
        raise ValueError('duration and fps must be finite and positive')
    if any(type(x) is not int for x in (multiple, offset, minimum)) or multiple < 1 or minimum < 1 or not 0 <= offset < multiple:
        raise ValueError('invalid frame cadence')
    # Same rounding as the supported Python Expression: nearest, ties to even.
    count = max(minimum, round(duration * fps))
    return count + (offset - count) % multiple


def from_config(config, duration):
    # Preserve generic workflows' historical 1k+0 default. Project templates use 17k+5.
    multiple, offset = config.get('frame_multiple', 1), config.get('frame_offset', 0)
    return frame_count(duration, config['fps'], multiple, offset,
                       config.get('frame_minimum', max(1, offset)))
