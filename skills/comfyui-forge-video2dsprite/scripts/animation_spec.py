"""Plan/save/show animation specifications. Offline; never submits or modifies a workflow.

JSON keys are a stable machine contract; Codex presents them in the user's language.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'comfyui-forge-generate2dmedia' / 'scripts'))
from frame_rules import frame_count

SCHEMA = 'comfyui-sprite-forge.spec/v1'
FACTORS = {'performance': 4, 'balanced': 5, 'quality': 6}
DEFAULT_SETTINGS = '.comfyui-sprite-forge.preferences.local.json'


def positive(value):
    result = Fraction(str(value))
    if result <= 0:
        raise ValueError('values must be positive')
    return result


def size(value, separator='x'):
    parts = str(value).lower().replace('×', 'x').split(separator)
    if len(parts) != 2 or any(not p.isdecimal() or int(p) < 1 for p in parts):
        raise ValueError(f'expected positive W{separator}H: {value}')
    return list(map(int, parts))


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def workflow(path=None):
    cfg = load(path) if path else {}
    if not isinstance(cfg, dict):
        raise ValueError('workflow config must be a JSON object')
    if path:
        positive(float(cfg['fps']))
    planning = cfg.get('planning', {})
    if not isinstance(planning, dict):
        raise ValueError('planning must be a JSON object')
    align = planning.get('dimension_multiple', 32)
    if type(align) is not int or align < 1:
        raise ValueError('planning.dimension_multiple must be a positive integer')
    align = math.lcm(32, align)  # adapter currently also requires multiples of 32
    minimum = planning.get('minimum_source_size', [32, 32])
    if not isinstance(minimum, list) or len(minimum) != 2 or any(type(x) is not int or x < 1 for x in minimum):
        raise ValueError('planning.minimum_source_size must contain two positive integers')
    # When reading a real config, match the adapter's generic omitted-field defaults.
    multiple = cfg.get('frame_multiple', 1 if path else 17)
    offset = cfg.get('frame_offset', 0 if path else 5)
    return {'fps': cfg.get('fps', 24), 'multiple': multiple,
            'offset': offset,
            'minimumFrames': cfg.get('frame_minimum', max(1, offset)),
            'alignment': align, 'minimumSize': minimum,
            'minimumSizeVerified': 'minimum_source_size' in planning,
            'configPath': str(Path(path).resolve()) if path else None,
            'configSha256': hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None}


def final_spec(cell, duration, fps, mode):
    cell = size(cell) if isinstance(cell, str) else cell
    duration, fps = positive(duration), positive(fps)
    if mode not in ('unspecified', 'loop', 'oneshot', 'hold'):
        raise ValueError('invalid playback mode')
    if fps > 100:
        raise ValueError('standard GIF delivery supports at most 100 fps; choose a lower preview rate first')
    count = duration * fps
    result = {'size': cell, 'durationSeconds': float(duration), 'durationRational': str(duration), 'fps': float(fps),
              'fpsRational': str(fps), 'frameCount': int(count) if count.denominator == 1 else None,
              'mode': mode, 'status': 'ready' if count.denominator == 1 and mode != 'unspecified' else 'needs_confirmation'}
    if count.denominator != 1:
        choices = sorted({max(1, math.floor(count)), math.ceil(count)})
        result['frameCountAlternatives'] = [{'frameCount': n, 'durationSeconds': float(Fraction(n) / fps),
                                              'fps': float(fps)} for n in choices]
    return result


def source_spec(cell, requested, rate, rules):
    if any(c < f for c, f in zip(cell, rules['finalSize'])):
        raise ValueError('source width and height must each be at least the final cell size')
    if any(c % rules['alignment'] for c in cell):
        suggestion = [math.ceil(c / rules['alignment']) * rules['alignment'] for c in cell]
        raise ValueError(f'source dimensions need alignment {rules["alignment"]}; suggested canvas {suggestion}; pad, do not stretch')
    if any(c < m for c, m in zip(cell, rules['minimumSize'])):
        raise ValueError('source dimensions are below the configured workflow minimum')
    requested, rate = positive(requested), positive(rate)
    if rules['configPath'] and rate != positive(rules['fps']):
        raise ValueError('source fps differs from workflow config; update a private config copy and verify its fps binding/Expression first')
    count = frame_count(float(requested), float(rate), rules['multiple'], rules['offset'], rules['minimumFrames'])
    return {'size': cell, 'megapixels': round(cell[0] * cell[1] / 1_000_000, 6),
            'requestedSeconds': float(requested), 'fps': float(rate), 'frameCount': count,
            'actualSeconds': float(Fraction(count) / rate),
            'cadence': {'multiple': rules['multiple'], 'offset': rules['offset'], 'minimum': rules['minimumFrames']}}


def plan(cell='128x128', duration=1, fps=8, mode='unspecified', config=None,
         ratio='1:1', source_duration=None, source_fps=None, source_size=None,
         envelope='1,1', preferred='balanced'):
    final = final_spec(cell, duration, fps, mode)
    rules = workflow(config)
    rules['finalSize'] = final['size']
    aspect = size(ratio, ':')
    extra = [positive(x) for x in envelope.split(',')]
    if len(extra) != 2 or any(x < 1 for x in extra):
        raise ValueError('envelope must be width,height factors >= 1')
    requested = positive(source_duration) if source_duration is not None else max(Fraction(3), positive(duration) * 3)
    rate = source_fps if source_fps is not None else rules['fps']
    options = {}
    for name, factor in FACTORS.items():
        w, h = [Fraction(v) * factor * e for v, e in zip(final['size'], extra)]
        ratio_value = Fraction(*aspect)
        w, h = max(w, h * ratio_value), max(h, w / ratio_value)
        dims = [math.ceil(max(v, m) / rules['alignment']) * rules['alignment'] for v, m in zip((w, h), rules['minimumSize'])]
        options[name] = source_spec(dims, requested, rate, rules)
        for previous in list(options)[:-1]:
            if dims == options[previous]['size']:
                options[name]['sameDimensionsAs'] = previous
                break
    if source_size:
        options['custom'] = source_spec(size(source_size), requested, rate, rules)
        preferred = 'custom'
    if preferred not in options:
        raise ValueError('selected tier is not available')
    warnings = ['generation_canvas_and_final_cells_are_separate', 'inspect_motion_envelope_before_submission',
                'source_requests_2_to_3_complete_candidates_not_3_seconds_of_final_playback']
    if not rules['minimumSizeVerified']:
        warnings.append('workflow_minimum_size_not_verified')
    if requested < 3:
        warnings.append('source_shorter_than_recommended_3_seconds')
    return {'schema': SCHEMA, 'confirmed': False, 'final': final, 'sourceOptions': options,
            'recommendedTier': preferred, 'workflow': {k: v for k, v in rules.items() if k != 'finalSize'},
            'inputs': {'cell': 'x'.join(map(str, final['size'])), 'duration': str(positive(duration)),
                       'fps': str(positive(fps)), 'mode': mode, 'config': rules['configPath'],
                       'ratio': ratio, 'source_duration': str(requested), 'source_fps': str(positive(rate)),
                       'source_size': source_size, 'envelope': envelope, 'preferred': preferred},
            'warnings': warnings, 'candidateTarget': {'minimum': 2, 'preferred': 3, 'priority': 'completeness_before_count'}}


def save(document, tier, path, confirmed=False, replace=False):
    if not confirmed:
        raise ValueError('save requires explicit confirmation after the user accepts the displayed specification')
    if document.get('schema') != SCHEMA or document['final']['status'] != 'ready':
        raise ValueError('resolve final frame count and playback mode before saving')
    # Recompute rather than trusting modified numbers in a hand-edited plan.
    rebuilt = plan(**document['inputs'])
    if document['final'] != rebuilt['final'] or document['sourceOptions'] != rebuilt['sourceOptions'] or document['workflow'] != rebuilt['workflow']:
        raise ValueError('plan or workflow changed; recompute and reconfirm')
    chosen = rebuilt['sourceOptions'][tier]
    target = Path(path)
    if target.exists() and not replace:
        raise ValueError('settings already exist; explicit --replace is needed after confirmation')
    result = {'schema': SCHEMA, 'confirmed': True, 'final': rebuilt['final'], 'source': chosen,
              'selectedTier': tier, 'workflow': rebuilt['workflow'], 'inputs': rebuilt['inputs']}
    result['inputs']['preferred'] = tier
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w' if replace else 'x', encoding='utf8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    return result


def show(path):
    path = Path(path)
    if not path.exists():
        return {'status': 'first_use', 'proposal': plan()}
    data = load(path)
    if data.get('schema') != SCHEMA or not data.get('confirmed'):
        raise ValueError('not a confirmed specification')
    try:
        rebuilt = plan(**data['inputs'])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {'status': 'reconfirm', 'settings': data, 'reason': str(exc), 'actionEnvelopeStillNeedsReview': True}
    tier = data['selectedTier']
    stale = (data['final'] != rebuilt['final'] or data['source'] != rebuilt['sourceOptions'][tier]
             or data['workflow'] != rebuilt['workflow'])
    return {'status': 'reconfirm' if stale else 'ask_reuse', 'settings': data,
            'proposal': rebuilt if stale else None, 'actionEnvelopeStillNeedsReview': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    for name, default in [('cell', '128x128'), ('duration', '1'), ('fps', '8'), ('mode', 'unspecified'),
                          ('config', None), ('ratio', '1:1'), ('source-duration', None), ('source-fps', None),
                          ('source-size', None), ('envelope', '1,1'), ('preferred', 'balanced')]:
        p.add_argument('--' + name, default=default)
    p.add_argument('--out', help='optional work-directory JSON proposal, not user delivery')
    p = sub.add_parser('save')
    p.add_argument('--plan', required=True);p.add_argument('--tier', choices=[*FACTORS, 'custom'], required=True)
    p.add_argument('--settings', default=DEFAULT_SETTINGS);p.add_argument('--confirmed', action='store_true')
    p.add_argument('--replace', action='store_true')
    p = sub.add_parser('show');p.add_argument('--settings', default=DEFAULT_SETTINGS)
    args = vars(parser.parse_args(argv));command = args.pop('command')
    try:
        if command == 'plan':
            out = args.pop('out');result = plan(**{k.replace('-', '_'): v for k, v in args.items()})
            if out:
                target = Path(out);target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('x', encoding='utf8') as stream:json.dump(result, stream, indent=2)
        elif command == 'save':
            result = save(load(args['plan']), args['tier'], args['settings'], args['confirmed'], args['replace'])
        else:
            result = show(args['settings'])
        print(json.dumps(result, ensure_ascii=True));return 0
    except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError, OverflowError) as exc:
        print('error: ' + str(exc), file=sys.stderr);return 2


if __name__ == '__main__':
    raise SystemExit(main())
