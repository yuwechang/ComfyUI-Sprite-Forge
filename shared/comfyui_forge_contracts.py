"""Strict values and final playback contract shared by every public boundary."""
from fractions import Fraction
import math


def integer(value,name,minimum=0):
    if type(value) is not int or value<minimum: raise ValueError(name+' must be an integer >= '+str(minimum))
    return value


def positive(value,name='value'):
    if isinstance(value,bool): raise ValueError(name+' must be a positive finite number')
    try: result=Fraction(str(value))
    except (ValueError,ZeroDivisionError,OverflowError): raise ValueError(name+' must be a positive finite number') from None
    if result<=0: raise ValueError(name+' must be positive')
    return result


def size(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2: raise ValueError('size needs two positive integer dimensions')
    return [integer(v,'dimension',1) for v in value]


def final_rate(value):
    rate = positive(value, 'final fps')
    if not 4 <= rate <= 24:
        raise ValueError('final fps must be between 4 and 24 inclusive')
    return rate


def final(value):
    if not isinstance(value,dict):raise ValueError('final specification must be an object')
    dimensions=size(value.get('size'))
    count=integer(value.get('frameCount'),'frameCount',1)
    rate=final_rate(value.get('fpsRational',value.get('fps')))
    duration=positive(value.get('durationRational',value.get('durationSeconds')),'durationSeconds')
    if Fraction(count,1)/rate!=duration:raise ValueError('frameCount, duration and fps disagree')
    for field,exact in (('fps',rate),('durationSeconds',duration)):
        if field in value:
            shown=positive(value[field],field)
            if not math.isclose(float(shown),float(exact),rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError(field+' disagrees with its exact rational value')
    kinds={'loop':'cycle','oneshot':'oneshot-return','hold':'oneshot-hold'}
    if value.get('mode') not in kinds or value.get('motionType',kinds[value['mode']])!=kinds[value['mode']]:
        raise ValueError('motion type and playback mode disagree')
    if value.get('status')!='ready':raise ValueError('final specification is not ready')
    return {**value,'size':dimensions,'frameCount':count,'fps':float(rate),'fpsRational':str(rate),
            'durationSeconds':float(duration),'durationRational':str(duration),'motionType':kinds[value['mode']]}


def confirmed(document):
    if not isinstance(document,dict) or document.get('confirmed') is not True:
        raise ValueError('an explicitly confirmed specification is required')
    return {**document,'final':final(document.get('final'))}


def source(value):
    if not isinstance(value,dict):raise ValueError('source specification must be an object')
    dimensions=size(value.get('size'))
    if any(v%32 for v in dimensions):raise ValueError('source dimensions must be multiples of 32')
    requested=positive(value.get('requestedSeconds'),'requested source seconds')
    fps=positive(value.get('fps',24),'source fps')
    if fps!=24:raise ValueError('source fps must be 24')
    cadence=value.get('cadence',{})
    if not isinstance(cadence,dict) or any(cadence.get(k,v)!=v for k,v in (('multiple',17),('offset',5),('minimum',5))):raise ValueError('source cadence differs from the fixed source formula')
    if requested>15:raise ValueError('requested source duration must not exceed 15 seconds')
    count=max(5,round(float(requested)*24));count=min(345,count+(5-count%17)%17)
    if 'frameCount' in value and integer(value['frameCount'],'source frameCount',1)!=count:
        raise ValueError('source frameCount differs from the fixed source formula')
    if 'actualSeconds' in value and not math.isclose(float(positive(value['actualSeconds'])),count/24,rel_tol=1e-12,abs_tol=1e-12):
        raise ValueError('source actualSeconds differs from frameCount / 24')
    return {**value,'size':dimensions,'requestedSeconds':float(requested),'fps':24,'frameCount':count,'actualSeconds':count/24}


def timeline(durations,raw):
    """Validate the two representations of one selection clock before sampling."""
    if not durations or any(type(d) is not int or d<1 for d in durations):raise ValueError('timeline durations must be positive integers')
    ticks=raw.get('ticks');hz=raw.get('tickHz')
    if ticks is not None or hz is not None:
        if not isinstance(ticks,list) or len(ticks)!=len(durations) or any(type(t) is not int or t<1 for t in ticks) or type(hz) is not int or hz<1:
            raise ValueError('ticks require a matching positive integer timeline and tickHz')
        edges=[0]
        for t in ticks:edges.append(edges[-1]+t)
        milliseconds=[(2*t*1000+hz)//(2*hz) for t in edges]
        if durations!=[b-a for a,b in zip(milliseconds,milliseconds[1:])]:raise ValueError('tick and millisecond timelines disagree')
    import re
    events=raw.get('events',[])
    if not isinstance(events,list):raise ValueError('timeline events must be a list')
    for event in events:
        if not isinstance(event,dict) or not isinstance(event.get('name'),str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:-]*',event['name']):raise ValueError('invalid timing event')
        if 'tick' not in event and 'atMs' not in event:raise ValueError('event needs a timestamp')
        if 'tick' in event:
            if ticks is None or type(event['tick']) is not int or not 0<=event['tick']<=sum(ticks):raise ValueError('event tick is outside its exact timeline')
        if 'atMs' in event:
            at=event['atMs']
            if isinstance(at,bool) or not isinstance(at,(int,float)) or not math.isfinite(at) or not 0<=at<=sum(durations):raise ValueError('event milliseconds are outside its timeline')
            if 'tick' in event and abs(Fraction(str(at))-Fraction(event['tick']*1000,hz))>Fraction(1,2):raise ValueError('event tick and millisecond timestamps disagree')


def selection_motion(raw,policy):
    """Optional motion metadata must agree with the actual playback contract."""
    modes={'cycle':'cycle','oneshot-return':'oneshot','oneshot-hold':'oneshot'}
    declared=[raw[key] for key in ('kind','motionType') if raw.get(key) is not None]
    if any(not isinstance(kind,str) or kind not in modes for kind in declared):raise ValueError('selection motion type must use a generic behavioral contract')
    if len(set(declared))>1:raise ValueError('selection kind and motionType disagree')
    if declared and policy is not None and modes[declared[0]]!=policy:raise ValueError('selection motion type and playback policy disagree')
