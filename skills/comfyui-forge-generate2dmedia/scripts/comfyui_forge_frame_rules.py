"""The single source-video frame expression: 24 fps, minimum 5, 17k+5."""
import math

FPS = 24
MULTIPLE = 17
OFFSET = MINIMUM = 5
MAX_SECONDS = 15
MAX_FRAMES = 345  # greatest 17k+5 not exceeding 15 * 24


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("workflow config must be a JSON object")
    for key, expected in (("fps", FPS), ("frame_multiple", MULTIPLE),
                          ("frame_offset", OFFSET), ("frame_minimum", MINIMUM)):
        value = config.get(key, expected)
        if isinstance(value, bool) or value != expected:
            raise ValueError(f"{key} must be {expected}; source timing uses the fixed 24 fps expression")


def frame_count(duration, fps=FPS):
    if isinstance(duration, bool) or isinstance(fps, bool):
        raise ValueError("duration must be positive seconds and source fps must be 24")
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0 or fps != FPS:
        raise ValueError("duration must be finite positive seconds and source fps must be 24")
    if duration > MAX_SECONDS:
        raise ValueError('requested source duration must not exceed 15 seconds')
    count = max(5, round(duration * 24))
    return min(MAX_FRAMES, count + (5 - (count % 17)) % 17)


def from_config(config, duration):
    validate_config(config)
    return frame_count(duration)


def canvas_rules(config):
    planning=config.get('planning',{})
    if not isinstance(planning,dict):raise ValueError('planning must be an object')
    multiple=planning.get('dimension_multiple',32);minimum=planning.get('minimum_source_size',[32,32])
    if type(multiple) is not int or multiple<1:raise ValueError('dimension_multiple must be a positive integer')
    if not isinstance(minimum,list) or len(minimum)!=2 or any(type(v) is not int or v<1 for v in minimum):raise ValueError('minimum_source_size needs two positive integers')
    return math.lcm(32,multiple),minimum


def validate_canvas(config,width,height):
    multiple,minimum=canvas_rules(config)
    if any(type(v) is not int or v<1 for v in (width,height)):raise ValueError('canvas dimensions must be positive integers')
    if width%multiple or height%multiple or width<minimum[0] or height<minimum[1]:raise ValueError('canvas does not meet configured alignment or minimum dimensions')


def diagnostic_canvas(config):
    """A compatible square used only to validate configuration, never generate."""
    multiple,minimum=canvas_rules(config)
    edge=((max(1280,*minimum)+multiple-1)//multiple)*multiple
    return edge,edge
