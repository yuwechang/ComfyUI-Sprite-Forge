#!/usr/bin/env python3
"""Export finished RGBA frames as a transparent atlas, APNG, GIF and timing JSON.

Does not generate, key, register or resize images. Optional sourceIndices selection
must refer to the supplied finished frames in the same sorted order.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
from PIL import Image

def export(frames_dir, out_dir, count=8, duration=1, selection=None):
    frames_dir,out_dir=Path(frames_dir),Path(out_dir)
    if count<1 or not math.isfinite(duration) or duration<=0:
        raise ValueError('count and duration must be positive')
    ms=round(duration*1000)
    if ms<count*10:
        raise ValueError('GIF needs at least 10 ms per frame; reduce count or increase duration')
    files=sorted(frames_dir.glob('*.png'))
    indices=list(range(len(files)))
    if selection:
        document=json.loads(Path(selection).read_text(encoding='utf-8-sig'))
        indices=document['sourceIndices']
    if (not indices or any(type(i) is not int or not 0<=i<len(files) for i in indices)):
        raise ValueError('selection must contain valid sourceIndices for the supplied frame directory')
    if len(indices)<count or len(set(indices))<count:
        raise ValueError('requested count exceeds unique selected source frames; interpolation is not performed')
    # Evenly sample phases, excluding a duplicated end pose.
    chosen=[indices[i*len(indices)//count] for i in range(count)]
    images=[]
    for i in chosen:
        with Image.open(files[i]) as im:images.append(im.convert('RGBA'))
    size=images[0].size
    if any(im.size!=size for im in images):raise ValueError('finished frames must share one canvas')
    if out_dir.exists():raise ValueError('out-dir already exists; choose a new directory')
    timings=[round((i+1)*ms/count)-round(i*ms/count) for i in range(count)]
    ticks=round(ms/10)
    gif_timings=[10*(((i+1)*ticks//count)-(i*ticks//count)) for i in range(count)]
    out_dir.mkdir(parents=True)
    frame_out=out_dir/'frames';frame_out.mkdir()
    atlas=Image.new('RGBA',(size[0]*count,size[1]),(0,0,0,0))
    for i,im in enumerate(images):
        im.save(frame_out/f'frame_{i:03}.png');atlas.paste(im,(size[0]*i,0))
    atlas.save(out_dir/'spritesheet.png')
    images[0].save(out_dir/'preview.apng',save_all=True,append_images=images[1:],duration=timings,loop=0,disposal=0,blend=0)
    gif=[]
    for im in images:
        indexed=im.convert('RGB').quantize(colors=255)
        palette=indexed.getpalette()[:765]+[0,0,0];indexed.putpalette(palette)
        indexed.paste(255,mask=im.getchannel('A').point(lambda a:255 if a<128 else 0))
        indexed.info['transparency']=255;gif.append(indexed)
    gif[0].save(out_dir/'preview.gif',save_all=True,append_images=gif[1:],duration=gif_timings,loop=0,
        transparency=255,background=255,disposal=2,optimize=False)
    meta={'size':list(size),'frameCount':count,'durationMs':ms,'fps':count*1000/ms,
        'durationsMs':timings,'gifDurationMs':sum(gif_timings),'gifDurationsMs':gif_timings,
        'loop':True,'sourceIndices':chosen,'sourceFiles':[files[i].name for i in chosen],
        'sourceHashes':[hashlib.sha256(files[i].read_bytes()).hexdigest() for i in chosen]}
    (out_dir/'animation.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    return meta

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames',required=True);p.add_argument('--selection');p.add_argument('--out-dir',required=True)
    p.add_argument('--count',type=int,default=8);p.add_argument('--duration',type=float,default=1)
    args=p.parse_args()
    try:print(json.dumps(export(args.frames,args.out_dir,args.count,args.duration,args.selection)))
    except (ValueError,OSError,KeyError,TypeError) as exc:p.exit(1,f'error: {exc}\n')
if __name__=='__main__':main()
