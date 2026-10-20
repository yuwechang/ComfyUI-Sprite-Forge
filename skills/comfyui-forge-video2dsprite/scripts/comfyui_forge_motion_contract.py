"""Motion names are labels; only these three behavioral contracts route processing."""
TYPES = ('cycle', 'oneshot-return', 'oneshot-hold')
MODES = {'cycle':'loop','oneshot-return':'oneshot','oneshot-hold':'hold'}

def contract(kind):
    if kind not in TYPES:
        raise ValueError('motion type must be cycle, oneshot-return or oneshot-hold')
    return {'motionType':kind, 'mode':MODES[kind], 'returnsToRest':kind == 'oneshot-return',
            'continuous':kind == 'cycle'}

def definitions(path):
    import json, re, math
    from pathlib import Path
    rows=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(rows,list) or not rows: raise ValueError('motions file must be a nonempty list')
    found={}
    for row in rows:
        if not isinstance(row,dict): raise ValueError('each motion definition must be an object')
        ident=row.get('id')
        if not isinstance(ident,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',ident) or ident in found:
            raise ValueError('motion ids must be unique safe labels')
        contract(row.get('type'))
        if not isinstance(row.get('description'),str) or not row['description'].strip():
            raise ValueError('every motion needs its own description; no named action template is inferred')
        if 'durationSeconds' in row and (isinstance(row['durationSeconds'],bool) or not isinstance(row['durationSeconds'],(int,float)) or not math.isfinite(row['durationSeconds']) or row['durationSeconds']<=0):
            raise ValueError('durationSeconds must be positive finite seconds')
        if row.get('lock','none') not in ('none','feet'): raise ValueError('invalid explicit registration lock')
        for key in ('airborne','movesFeet'):
            if key in row and type(row[key]) is not bool: raise ValueError(key+' must be boolean')
        if row.get('type') != 'cycle' and 'durationSeconds' not in row:
            raise ValueError('one-shot definitions require confirmed durationSeconds')
        if row.get('framing','square') not in ('square','tall','wide'):raise ValueError('framing is a geometric choice')
        if row.get('candidateRange') is not None:
            raise ValueError('select a candidate on its actual generated take; do not bind unseen source frame numbers in a generation plan')
        validate_timing(row.get('keys',{}),row.get('events',[]))
        found[ident]=row
    return found


def validate_timing(keys,events):
    import re,math
    if not isinstance(keys,dict):raise ValueError('keys must be an object of explicit source/phase/hold values')
    for label,key in keys.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',label) or not isinstance(key,dict):raise ValueError('invalid key')
        if type(key.get('source')) is not int or key['source']<0:raise ValueError('key source must be a nonnegative integer')
        at=key.get('at')
        if isinstance(at,bool) or not isinstance(at,(int,float)) or not math.isfinite(at) or not 0<at<1:raise ValueError('key phase must be between 0 and 1')
        hold=key.get('holdMs',0)
        if type(hold) is not int or hold<0:raise ValueError('holdMs must be a nonnegative integer')
    if not isinstance(events,list):raise ValueError('events must be a list')
    for event in events:
        if not isinstance(event,dict) or not isinstance(event.get('name'),str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.:-]*',event['name']) or type(event.get('source')) is not int or event['source']<0:
            raise ValueError('each event needs its explicit name and nonnegative integer source')
