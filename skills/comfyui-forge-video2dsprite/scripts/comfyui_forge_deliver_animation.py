"""Deliver already selected/finished PNG frames, sheet, GIF and source MP4 only.

No generation, selection, keying, registration or resizing is performed here.
JSON receipts stay at --report in the working directory, outside the delivery.
"""
import comfyui_forge_contracts
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import zipfile
from PIL import Image, ImageSequence


def write_gif(images, duration, target):
    """One preview encoder shared by review and delivery; exact centisecond total."""
    ticks = round(duration * 100)
    if not images or ticks < len(images):
        raise ValueError('GIF needs at least 10ms per frame')
    delays = [10 * (((i+1)*ticks//len(images)) - (i*ticks//len(images))) for i in range(len(images))]
    if max(delays)>655350:raise ValueError('GIF frame delay exceeds its 65535-centisecond format limit; increase final frame count/fps')
    gif = []
    for im in images:
        indexed=im.convert('RGB').quantize(colors=255)
        indexed.putpalette(indexed.getpalette()[:765]+[0,0,0])
        indexed.paste(255,mask=im.getchannel('A').point(lambda a:255 if a<128 else 0))
        gif.append(indexed)
    gif[0].save(target,save_all=True,append_images=gif[1:],duration=delays,loop=0,
                transparency=255,background=255,disposal=2,optimize=False)
    return delays


def deliver(frames, source, output, specification, columns=None, report=None):
    frames, source, output = Path(frames).resolve(), Path(source).resolve(), Path(output).resolve()
    specification=comfyui_forge_contracts.confirmed(specification)
    spec=specification['final']
    count, cell = spec['frameCount'], tuple(spec['size'])
    if spec['status'] != 'ready' or count is None or spec['mode'] == 'unspecified':
        raise ValueError('resolve final timing and playback mode first')
    rate, duration = Fraction(str(spec['fpsRational'])), Fraction(str(spec['durationRational']))
    if count < 1 or Fraction(count) / rate != duration:
        raise ValueError('inconsistent final count, fps and duration')
    paths = sorted(frames.glob('*.png'))
    if len(paths) != count:
        raise ValueError(f'expected exactly {count} finished selected PNGs, got {len(paths)}; do not pass unselected frames')
    if source.suffix.lower() != '.mp4' or not source.is_file() or source.stat().st_size == 0:
        raise ValueError('source must be an existing nonempty MP4')
    if output == frames or output.is_relative_to(frames):
        raise ValueError('delivery must be separate from the working frame directory')
    if report:
        report = Path(report).resolve()
        if report == output or report.is_relative_to(output) or (report.exists() and not output.exists()):
            raise ValueError('report must be a new work-directory file outside delivery')
    pending=report.with_name(report.name+'.pending') if report else None
    if output.exists():
        receipt_path=report if report and report.is_file() else pending
        if not receipt_path or not receipt_path.is_file():
            raise ValueError('output already exists without a verifiable delivery receipt; inspect it before continuing')
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        current_frames=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        if (receipt.get('columns')!=(min(8,count) if columns is None else comfyui_forge_contracts.integer(columns,'columns',1)) or receipt.get('specification')!=spec or receipt.get('frameSha256')!=current_frames
                or receipt.get('sourceSha256')!=hashlib.sha256(source.read_bytes()).hexdigest()):
            raise ValueError('existing delivery belongs to different inputs or specification')
        expected=receipt.get('outputSha256',{})
        actual={p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.rglob('*') if p.is_file()}
        if not expected or actual!=expected:raise ValueError('existing delivery contents changed; inspect before continuing')
        if receipt_path==pending:pending.replace(report)
        return receipt
    if pending and pending.exists():
        # Nothing published: preserve the previous pending transaction for diagnosis.
        n=1
        while pending.with_name(pending.name+f'.unpublished-{n}').exists():n+=1
        pending.rename(pending.with_name(pending.name+f'.unpublished-{n}'))
    images = []
    for path in paths:
        with Image.open(path) as im:
            if im.size != cell or im.mode != 'RGBA':
                raise ValueError('all finished frames must be RGBA at the confirmed final cell size')
            images.append(im.copy())
    cols = min(8,count) if columns is None else comfyui_forge_contracts.integer(columns,'columns',1)
    if not 1 <= cols <= count:
        raise ValueError('columns must be between 1 and frame count')
    rows = math.ceil(count / cols)
    ms = round(duration * 1000)
    ticks = round(duration * 100)
    if ticks < count:
        raise ValueError('GIF needs at least 10ms per frame')
    delays = [10 * (((i + 1) * ticks // count) - (i * ticks // count)) for i in range(count)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.forge-delivery-', dir=output.parent) as temp:
        stage = Path(temp) / 'delivery';stage.mkdir()
        dest = stage / 'frames';dest.mkdir()
        sheet = Image.new('RGBA', (cell[0] * cols, cell[1] * rows), (0, 0, 0, 0))
        for i, (path, im) in enumerate(zip(paths, images)):
            shutil.copy2(path, dest / f'frame_{i:04}.png')
            sheet.paste(im, ((i % cols) * cell[0], (i // cols) * cell[1]))
        sheet.save(stage / 'animation-sheet.png')
        # A repeating GIF previews even a one-shot. Runtime playback mode is reported separately.
        write_gif(images, duration, stage / 'preview.gif')
        shutil.copy2(source, stage / 'source.mp4')
        with zipfile.ZipFile(stage / 'animation.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file() and path.suffix != '.zip':
                    archive.write(path, path.relative_to(stage).as_posix())
        with Image.open(stage / 'preview.gif') as preview:
            decoded_ms = sum(f.info['duration'] for f in ImageSequence.Iterator(preview))
            decoded_frames = preview.n_frames
        if decoded_ms != sum(delays):
            raise ValueError('GIF decode timing verification failed')
        receipt = {'specification':spec, 'cellSize': list(cell), 'frameCount': count, 'fpsRational': str(rate),
                   'durationMs': ms, 'mode': spec['mode'], 'columns': cols, 'rows': rows,
                   'order': 'left-to-right, top-to-bottom', 'previewLoops': True,
                   'gifDurationMs': decoded_ms, 'gifEncodedFrames': decoded_frames,
                   'gifFrameDurationsMs': delays, 'workDirectory': str(frames.parent),
                   'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                   'frameSha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths],
                   'files': {key: str(output / name) for key, name in
                             [('zip', 'animation.zip'), ('gif', 'preview.gif'),
                              ('sheet', 'animation-sheet.png'), ('source', 'source.mp4')]}}
        receipt['outputSha256']={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in stage.rglob('*') if p.is_file()}
        if pending:
            pending.parent.mkdir(parents=True,exist_ok=True)
            with pending.open('x',encoding='utf-8') as stream:json.dump(receipt,stream,indent=2)
        stage.rename(output)
    if report:
        pending.replace(report)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', required=True);parser.add_argument('--source', required=True)
    parser.add_argument('--out-dir', required=True);parser.add_argument('--spec', required=True)
    parser.add_argument('--columns', type=int);parser.add_argument('--report')
    args = parser.parse_args(argv)
    try:
        spec = json.loads(Path(args.spec).read_text(encoding='utf-8-sig'))
        result = deliver(args.frames, args.source, args.out_dir, spec, args.columns, args.report)
        print(json.dumps(result, ensure_ascii=True));return 0
    except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError) as exc:
        parser.exit(2, 'error: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
