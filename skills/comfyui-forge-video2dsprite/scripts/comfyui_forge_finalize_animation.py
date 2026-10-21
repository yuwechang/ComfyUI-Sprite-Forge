"""Verify one selected candidate, materialize final frames, review, then deliver."""
import comfyui_forge_contracts
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw
import comfyui_forge_core
import comfyui_forge_gait_loop
from comfyui_forge_selection_tools import playback_plan
from comfyui_forge_deliver_animation import deliver, write_gif


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_provenance(finish,finished,source):
    dependencies=[];registration=finish.get('source',{}).get('registration')
    if not registration:return {'status':'unverified','reason':'no registration provenance was supplied'},dependencies
    path=(finished/registration['path']).resolve()
    if digest(path)!=registration['sha256']:raise ValueError('registration provenance changed')
    dependencies.append({'path':str(path),'sha256':digest(path)})
    data=load(path);directory=data.get('video',{}).get('frameDirectory')
    metadata=(path.parent/directory).resolve().parent/'pipeline-meta.json' if directory else None
    if not metadata or not metadata.is_file():return {'status':'unverified','reason':'no source-video processing receipt'},dependencies
    processing=load(metadata);expected=processing.get('video',{}).get('sha256')
    if not expected:return {'status':'unverified','reason':'processing receipt lacks a video checksum'},dependencies
    if digest(source)!=expected:raise ValueError('retained MP4 differs from the video used to produce these frames')
    dependencies.append({'path':str(metadata),'sha256':digest(metadata)})
    return {'status':'verified','sourceSha256':expected,'extraction':processing.get('extract'),
            'sourceFps':processing.get('probe',{}).get('fps_rational')},dependencies


def prepare(finished, selection_path, specification, source, work, required=()):
    finished, selection_path, source, work = map(lambda p: Path(p).resolve(), (finished, selection_path, source, work))
    if work.exists():
        raise ValueError('work directory already exists; preserve previous reviews')
    spec=comfyui_forge_contracts.confirmed(load(specification))
    final=spec['final']
    selection = comfyui_forge_gait_loop.read_selection(selection_path)
    selected_type = selection['raw'].get('motionType')
    if selected_type and selected_type != final.get('motionType'):
        raise ValueError('selected motion type differs from the confirmed final contract')
    finish = load(finished / 'finish.json')
    provenance,dependencies=source_provenance(finish,finished,source)
    original = (finished / finish['source']['frames']).resolve()
    original_files = comfyui_forge_gait_loop.verify_selection(selection, selection_path, original)
    dependencies.extend(comfyui_forge_gait_loop.selection_dependencies(selection,selection_path,original))
    dependencies.extend({'path':str(original_files[i]),'sha256':digest(original_files[i])}
                        for i in range(selection['start'],selection['endExclusive']))
    source_mapping = {i:{'sourceIndex':i,'sourceFile':p.name} for i,p in enumerate(original_files)}
    registration = finish.get('source',{}).get('registration')
    if registration:
        registration_path = (finished/registration['path']).resolve()
        registered = load(registration_path)
        rows = registered['frames']
        if len(rows) != len(original_files):
            raise ValueError('registration/source frame count mismatch')
        raw_folder = (registration_path.parent/registered['video']['frameDirectory']).resolve()
        raw_files = comfyui_forge_gait_loop.frame_paths(raw_folder,1)
        evidence = {row['sourceIndex'] for row in selection['raw'].get('closureEvidence',[])}
        for i in set(range(selection['start'],selection['endExclusive'])) | evidence:
            row = rows[i]
            source_index = row['sourceIndex']
            if (type(source_index) is not int or not 0<=source_index<len(raw_files)
                    or source_index != registered['video']['range'][0]+i
                    or (registration_path.parent/row['file']).resolve() != original_files[i]
                    or row['sha256'] != digest(original_files[i])
                    or raw_files[source_index].name != row['sourceFile']
                    or digest(raw_files[source_index]) != row['sourceSha256']):
                raise ValueError('registration source mapping or checksum changed')
            dependencies.append({'path':str(raw_files[source_index]),'sha256':row['sourceSha256']})
            source_mapping[i] = {'sourceIndex':source_index,'sourceFile':row['sourceFile'],
                                 'sourceSha256':row['sourceSha256']}
    for row in selection['raw'].get('closureEvidence', []):
        dependencies.append({'path': str(original_files[row['sourceIndex']]), 'sha256': row['sha256']})
    provenance_selection = selection['raw'].get('candidateProvenance', {}).get('sourceSelection')
    if provenance_selection:
        dependencies.append(provenance_selection)
    if final['mode'] == 'loop' and selection['policy'] != 'cycle':
        raise ValueError('a continuous cycle requires a forward cycle selection, not reversed playback')
    timing = playback_plan(selection, final['frameCount'], final['mode'], required)
    picked = timing['sourceIndices']
    for event in timing['events']:
        event['atMs'] = float(Fraction(event['outputFrame'] * 1000) / Fraction(str(final['fpsRational'])))
    records = finish['frames']
    if len(records) != len(original_files):
        raise ValueError('finished/source frame count mismatch')
    images, inputs = [], []
    for i in picked:
        record = records[i]
        path = (finished / record['file']).resolve()
        if not path.is_relative_to(finished) or record['sourceFile'] != original_files[i].name:
            raise ValueError('finished frame mapping differs from the selected source')
        if record['sourceSha256'] != digest(original_files[i]) or record['sha256'] != digest(path):
            raise ValueError('finished/source checksum changed')
        with Image.open(path) as image:
            if image.mode != 'RGBA' or list(image.size) != final['size']:
                raise ValueError('finished frame mode/size differs from final specification')
            images.append(image.copy())
        inputs.append({'path':str(path), 'sha256':digest(path), 'sourceIndex':i})
    if source.suffix.lower() != '.mp4' or not source.is_file():
        raise ValueError('source must be the retained MP4')
    clip = comfyui_forge_gait_loop.load_clip(finished / 'frames', Fraction(str(final['fpsRational'])))
    seam = comfyui_forge_gait_loop.sequence_seam(clip, picked) if final['mode'] == 'loop' else None
    bounds = [im.getbbox() for im in images]
    clipped = [i for i,b in enumerate(bounds) if b is None or min(b[:2]) == 0 or b[2] == images[i].width or b[3] == images[i].height]
    with comfyui_forge_core.staged_output(work) as stage:
        (stage/'frames').mkdir()
        for n,im in enumerate(images):
            im.save(stage/'frames'/f'frame_{n:04}.png')
        write_gif(images,Fraction(final['durationRational']),stage/'preview.gif')
        w,h = images[0].size
        contact = Image.new('RGB', (len(images)*w, h*2+32), 'white')
        draw = ImageDraw.Draw(contact)
        for n,im in enumerate(images):
            for row,bg in enumerate(((245,245,245),(24,24,28))):
                x,y = n*w,row*(h+16)
                contact.paste(Image.new('RGB',(w,h),bg),(x,y))
                contact.paste(im,(x,y),im)
                draw.text((x+3,y+h),str(n),fill='black')
        contact.save(stage/'review-contact.png')
        receipt = {'schema':'comfyui-forge.final-review/v1', 'status':'needs-visual-review',
                   'sourceIndices':picked, 'timing':timing, 'candidateInterval':[selection['start'],selection['endExclusive']],
                   'sourceMapping':[{'outputFrame':n,'registeredIndex':i,**source_mapping[i]} for n,i in enumerate(picked)],
                   'candidateConfidence':selection['raw'].get('confidence'), 'finalSeam':seam,
                   'finalBounds':bounds, 'edgeTouchFrames':clipped,
                   'centroidXRange':[float(np.min(clip.cx[picked])),float(np.max(clip.cx[picked]))],
                   'notProven':['numeric scores do not certify action completeness, foot alternation, identity or artistic acceptance'],
                   'specification':spec, 'source':{'path':str(source),'sha256':digest(source)},
                   'selection':{'path':str(selection_path),'sha256':digest(selection_path)}, 'inputs':inputs+dependencies,'sourceProvenance':provenance,
                   'sourceFrames':[{'path':str(original_files[i]),'sha256':digest(original_files[i])} for i in picked],
                   'finish':{'path':str(finished/'finish.json'),'sha256':digest(finished/'finish.json')},
                   'reviewArtifacts':[{'path':name,'sha256':digest(stage/name)} for name in ('preview.gif','review-contact.png')],
                   'frames':[{'path':f'frames/frame_{n:04}.png','sha256':digest(stage/'frames'/f'frame_{n:04}.png')} for n in range(len(images))]}
        comfyui_forge_core.write_json(stage/'review.json', receipt)
    return receipt


def approve(work, output, note):
    work = Path(work).resolve()
    if not note or not note.strip():
        raise ValueError('record the visual review conclusion before delivery')
    receipt = load(work/'review.json')
    if receipt['edgeTouchFrames']:
        raise ValueError('final frames are empty or touch the canvas edge; resolve framing before approval')
    for row in receipt['inputs'] + receipt['sourceFrames'] + [receipt['source'], receipt['selection'], receipt['finish']]:
        if digest(row['path']) != row['sha256']:
            raise ValueError('an input changed after review preparation')
    if not receipt.get('reviewArtifacts'):raise ValueError('review lacks preview hashes; rebuild the final review before approval')
    for row in receipt['reviewArtifacts']+receipt['frames']:
        if digest(work/row['path']) != row['sha256']:
            raise ValueError('review preview or selected final frame changed after review preparation')
    delivered = deliver(work/'frames', receipt['source']['path'], output, receipt['specification'], report=work/'delivery.json')
    accepted=receipt.get('acceptedReviewSha256',digest(work/'review.json'))
    receipt.update(status='approved', reviewNote=note.strip(), delivery=delivered,acceptedReviewSha256=accepted)
    comfyui_forge_core.write_json(work/'review.json',receipt,no_clobber=False)
    return delivered


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare')
    for flag in ('finished','selection','spec','source','work-dir'):
        p.add_argument('--'+flag,required=True)
    p.add_argument('--required-frame',action='append',type=int,default=[])
    p=sub.add_parser('approve')
    p.add_argument('--work-dir',required=True);p.add_argument('--out-dir',required=True);p.add_argument('--review-note',required=True)
    args=parser.parse_args(argv)
    try:
        result=(prepare(args.finished,args.selection,args.spec,args.source,args.work_dir,args.required_frame)
                if args.command=='prepare' else approve(args.work_dir,args.out_dir,args.review_note))
        print(json.dumps({'status':result.get('status','delivered'),'workDirectory':args.work_dir}));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('error: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
