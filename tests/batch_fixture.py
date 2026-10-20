import json
from pathlib import Path

def confirmed(root,source_duration=3):
    import comfyui_forge_animation_spec
    path=Path(root)/'confirmed-spec.json'
    path.write_text(json.dumps({'confirmed':True,'final':comfyui_forge_animation_spec.final_spec('128x128',1,8,'cycle'),
                               'source':{'size':[640,640],'requestedSeconds':source_duration}}))
    return str(path)
