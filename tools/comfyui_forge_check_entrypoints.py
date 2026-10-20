"""Release gate: executable filenames and actual dispatch paths must agree."""
from pathlib import Path
import ast,sys
ROOT=Path(__file__).resolve().parents[1]

def check():
    problems=[]
    for file in ROOT.rglob('*.py'):
        if any(part in ('tests','.git','.venv','__pycache__') for part in file.relative_to(ROOT).parts):continue
        if not file.name.startswith('comfyui_forge_'):problems.append('unnamespaced production file: '+str(file))
        ast.parse(file.read_text(encoding='utf-8-sig'))
    sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
    import comfyui_forge_sprite_set as batch
    for name,file in batch.SCRIPTS.items():
        if not file.is_file():problems.append(name+' points to a missing file: '+str(file))
    if not batch.FINISH_SCRIPT.is_file():problems.append('missing actual finisher')
    if problems:raise ValueError('\n'.join(problems))
    return {'status':'ok','dispatchEntries':len(batch.SCRIPTS)+1}
if __name__=='__main__':
    import json
    print(json.dumps(check()))
