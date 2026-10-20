"""Conservative flat-background extraction without assuming a named screen colour."""
from collections import deque
import numpy as np


def estimate(pixels):
    rgb=pixels[...,:3].astype(np.float32)
    h,w=rgb.shape[:2]
    sides=[rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]]
    samples=np.concatenate(sides)
    # Quantized modal bin avoids a median invented between two different backgrounds.
    bins=(samples//8).astype(int)
    colours,counts=np.unique(bins,axis=0,return_counts=True)
    dominant=colours[counts.argmax()]
    near=np.max(np.abs(bins-dominant),axis=1)<=1
    colour=np.median(samples[near],axis=0)
    shares=[float((np.linalg.norm(side-colour,axis=1)<=16).mean()) for side in sides]
    valid=min(shares)>=0.85 and float((np.linalg.norm(samples-colour,axis=1)<=16).mean())>=0.92
    return {'colour':[int(round(v)) for v in colour], 'sideConsistency':shares,
            'valid':valid, 'method':'four outer edges, dominant colour cluster and per-side consistency'}


def connected_boundary(mask):
    h,w=mask.shape;seen=np.zeros_like(mask)
    q=deque([(0,x) for x in range(w)]+[(h-1,x) for x in range(w)]+
            [(y,0) for y in range(h)]+[(y,w-1) for y in range(h)])
    while q:
        y,x=q.popleft()
        if seen[y,x] or not mask[y,x]: continue
        left=x
        while left>0 and mask[y,left-1] and not seen[y,left-1]: left-=1
        right=x
        while right+1<w and mask[y,right+1] and not seen[y,right+1]: right+=1
        seen[y,left:right+1]=True
        for ny in (y-1,y+1):
            if 0<=ny<h:
                span=mask[ny,left:right+1]&~seen[ny,left:right+1]
                starts=np.flatnonzero(span & ~np.r_[False,span[:-1]])
                q.extend((ny,left+int(i)) for i in starts)
    return seen


def extract(pixels, declared=None, pixel_art=False):
    report=estimate(pixels)
    if not report['valid']:
        raise ValueError('background is not consistently flat on all four edges; provide an approved cutout or review mask')
    colour=np.array(report['colour'],np.float32)
    if declared is not None and np.linalg.norm(np.asarray(declared)-colour)>24:
        raise ValueError('declared background differs from the observed border colour')
    rgb=pixels[...,:3].astype(np.float32)
    distance=np.linalg.norm(rgb-colour,axis=2)
    connected=connected_boundary(distance<=32)
    subject=~connected
    if not subject.any(): raise ValueError('no distinguishable subject remains on the flat background')
    # Disconnected matching regions may be body material or holes: never guess them away.
    ambiguous=(distance<=24)&subject
    share=float(ambiguous.sum())/max(1,int(subject.sum()))
    report['ambiguousSubjectShare']=share
    report['requiresVisualReview']=True
    if share>0.005:
        raise ValueError('background colour conflicts with enclosed subject regions; review an explicit mask before recolouring')
    alpha=np.ones(distance.shape,np.float32)
    alpha[connected]=np.clip((distance[connected]-8)/24,0,1)
    if pixel_art: alpha=(alpha>=0.5).astype(np.float32)
    # Decontaminate only partially transparent boundary pixels, never recolour the opaque subject.
    edge=(alpha>0)&(alpha<1)
    rgb[edge]=np.clip((rgb[edge]-colour*(1-alpha[edge,None]))/alpha[edge,None],0,255)
    if float(colour.max()-colour.min()) >= 60 and colour.min()<=127.5<colour.max():
        import comfyui_forge_matte
        key='#'+''.join(f'{int(v):02x}' for v in colour)
        native=pixels.copy();native[...,3]=255
        soft,info=comfyui_forge_matte.key_still(native,quality='soft',key=key)
        candidate=np.asarray(soft).copy()
        interior=subject.copy()
        for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
            shifted=np.zeros_like(subject)
            ys=slice(max(0,dy),min(subject.shape[0],subject.shape[0]+dy))
            xs=slice(max(0,dx),min(subject.shape[1],subject.shape[1]+dx))
            shifted[ys,xs]=subject[slice(max(0,-dy),min(subject.shape[0],subject.shape[0]-dy)),slice(max(0,-dx),min(subject.shape[1],subject.shape[1]-dx))]
            interior &= shifted
        lost=interior & (candidate[...,3]<245)
        if float(lost.sum())/max(1,int(interior.sum()))>0.005:
            report['chromaFallback']='chroma matte affects subject material; retained boundary-connected colour-distance extraction'
        else:
            solid=subject & (candidate[...,3]>=250)
            candidate[...,:3][solid]=pixels[...,:3][solid]
            report['chromaMatte']=info
            rgb=candidate[...,:3].astype(np.float32);alpha=candidate[...,3].astype(np.float32)/255
    if pixel_art: alpha=(alpha>=0.5).astype(np.float32)
    out=pixels.copy();out[...,:3]=np.rint(rgb).astype(np.uint8)
    out[...,3]=np.rint(alpha*255).astype(np.uint8)
    report.update(backdrop='#'+''.join(f'{v:02x}' for v in report['colour']),
                  method=report['method']+'; boundary-connected colour-distance matte',
                  transparentShare=float((out[...,3]==0).mean()))
    return out,report
