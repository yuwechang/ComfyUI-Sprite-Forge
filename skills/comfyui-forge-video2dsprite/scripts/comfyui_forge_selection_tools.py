"""Shared phase sampling for a single already-selected action candidate."""

def sample_indices(indices, count, mode='loop', required=()):
    if type(count) is not int or count < 1 or not indices or any(type(i) is not int or i < 0 for i in indices):
        raise ValueError('frame count and source indices must be positive integers')
    if len(set(indices)) != len(indices) or any(a >= b for a, b in zip(indices, indices[1:])):
        raise ValueError('candidate must be one forward sequence without repeated/reversed source indices')
    if len(indices) < count:
        raise ValueError('not enough unique source frames; repeating/interpolating poses is not automatic')
    if mode not in ('loop', 'oneshot', 'hold'):
        raise ValueError('resolve final playback mode first')
    n = len(indices)
    # A one-shot must retain its initial and terminal poses; a cycle excludes the repeated endpoint.
    positions = ([min(n-1, int((j+.5)*n/count)) for j in range(count)] if mode == 'loop' else
                 [round(j*(n-1)/max(1,count-1)) for j in range(count)])
    if mode != 'loop' and count == 1 and n > 1:
        raise ValueError('a one-frame export cannot preserve both action endpoints')
    pinned = set(required)
    if not pinned.issubset(indices) or len(pinned) > count:
        raise ValueError('required event frames must fit the chosen candidate and target frame count')
    if mode != 'loop':
        pinned.update((indices[0], indices[-1]))
    if len(pinned) > count:
        raise ValueError('important poses and endpoints exceed the target count')
    chosen = {indices[i] for i in positions} | pinned
    while len(chosen) > count:
        removable = [i for i in chosen if i not in pinned]
        drop = min(removable, key=lambda i: (min(abs(indices.index(i)-indices.index(j)) for j in chosen if j != i), i))
        chosen.remove(drop)
    return sorted(chosen)


def playback_plan(selection, count, mode='loop', required=()):
    """Quantize an authored retime timeline to fixed-rate slots, not source spacing.

    Plain cycles retain phase sampling. Authored events/timing and one-shots use
    duration weights; repeated slots represent intentional holds, never new art.
    """
    from fractions import Fraction
    from bisect import bisect_right
    indices = selection['indices']
    durations = selection['durations']
    raw = selection.get('raw', {})
    import comfyui_forge_contracts
    comfyui_forge_contracts.timeline(durations,raw)
    events = raw.get('events', [])
    if type(count) is not int or count < 1 or mode not in ('loop', 'oneshot', 'hold'):
        raise ValueError('resolve positive integer count and final playback mode first')
    if not indices or len(indices) != len(durations) or any(type(d) is not int or d <= 0 for d in durations):
        raise ValueError('invalid playback timeline')
    if any(type(i) is not int or not selection['start'] <= i < selection['endExclusive'] for i in indices):
        raise ValueError('timeline crosses the selected candidate')
    if any(b<a for a,b in zip(indices,indices[1:])):
        raise ValueError('selected motion must play forward; adjacent repeats alone are holds')
    expected_policy='cycle' if mode=='loop' else 'oneshot'
    if selection.get('policy') not in (None,expected_policy):raise ValueError('selection playback policy differs from final motion contract')
    authored = bool(events or raw.get('ticks') or raw.get('auto') or 'retime' in raw.get('method','').lower())
    if mode == 'loop' and not authored:
        picked = sample_indices(indices, count, mode, required)
        return {'method':'cycle-phase', 'sourceIndices':picked, 'events':[], 'heldSlots':0}
    weights = raw.get('ticks', durations)
    if len(weights) != len(indices) or any(type(w) is not int or w <= 0 for w in weights):
        raise ValueError('invalid retime tick weights')
    edges = [0]
    for w in weights: edges.append(edges[-1]+w)
    pinned = set()
    if mode != 'loop': pinned.update((0,len(indices)-1))
    for source in required:
        if source not in indices: raise ValueError('required event frame is outside the selected timeline')
        pinned.add(indices.index(source))
    mapped = []
    for event in events:
        if not isinstance(event,dict) or not isinstance(event.get('name'),str):
            raise ValueError('invalid timing event')
        if 'tick' in event:
            hz = raw.get('tickHz')
            if type(hz) is not int or hz <= 0 or type(event['tick']) is not int:
                raise ValueError('event tick requires a positive integer tickHz')
            time = Fraction(event['tick'],hz)
            unit_total = Fraction(sum(weights),hz) if 'ticks' in raw else Fraction(sum(durations),1000)
        elif 'atMs' in event:
            time = Fraction(str(event['atMs']))/1000
            unit_total = Fraction(sum(durations),1000)
        else: raise ValueError('event needs tick or atMs timing')
        if not 0 <= time <= unit_total: raise ValueError('event lies outside the timeline')
        terminal = time == unit_total
        phase = time/unit_total
        position = min(len(indices)-1,bisect_right(edges,phase*edges[-1])-1)
        if event.get('sourceIndex',indices[position]) != indices[position]:
            raise ValueError('event timestamp differs from its required source pose')
        if not terminal: pinned.add(position)
        mapped.append((event,position,terminal,phase))
    if len(pinned) > count:
        raise ValueError('important poses and endpoints exceed the target count; increase final fps/count')
    # Minimise squared duration error subject to mandatory event/end poses.
    ideals = [Fraction(w*count,sum(weights)) for w in weights]
    slots = [int(i in pinned) for i in range(len(indices))]
    for _ in range(count-sum(slots)):
        pos = max(range(len(indices)),key=lambda i:(2*(ideals[i]-slots[i])-1,-i))
        slots[pos] += 1
    picked = [source for source,n in zip(indices,slots) for _ in range(n)]
    starts = [0]
    for n in slots: starts.append(starts[-1]+n)
    output_events = []
    for event,pos,terminal,phase in mapped:
        if terminal:
            slot = count
        else:
            # Retain the event's offset inside a held pose, not merely its pose identity.
            offset=(phase*edges[-1]-edges[pos])/weights[pos]
            exact=Fraction(starts[pos])+offset*slots[pos]
            slot=min(starts[pos+1]-1,max(starts[pos],round(exact)))
        output_events.append({'name':event['name'], 'sourceIndex':indices[pos],
                              'outputFrame':slot, 'phase':str(Fraction(slot,count)),
                              'originalPhase':str(phase),
                              'timingErrorFrames':float(Fraction(slot)-phase*count),
                              'original':event})
    return {'method':'retime-duration-quantization', 'sourceIndices':picked,
            'events':output_events, 'heldSlots':sum(max(0,n-1) for n in slots),
            'poseSlots':[{'sourceIndex':i,'slots':n,'idealSlots':float(ideal)}
                         for i,n,ideal in zip(indices,slots,ideals)],
            'droppedSourceIndices':[i for i,n in zip(indices,slots) if n == 0],
            'timingNotice':'Fixed fps quantizes timing; inspect event errors and held poses. No semantic hit is inferred.'}
