#!/usr/bin/env python3
"""Read-only check of the sole local ComfyUI provider; never inspects credentials."""
import argparse
import json
from pathlib import Path
import sys
import comfyui_media

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-tools', default='none', help='Compatibility argument; host media tools are never used')
    parser.add_argument('--save')
    args=parser.parse_args()
    try:
        result={**comfyui_media.check(), 'routes':['local:comfyui'], 'cloudProviders':[], 'imageGeneration':False}
        code=0 if result['status']=='ok' else 1
    except (OSError, ValueError, KeyError, comfyui_media.ComfyError) as exc:
        result={'status':'error','routes':['local:comfyui'],'error':str(exc)}
        code=1
    if args.save:
        path=Path(args.save); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return code

if __name__=='__main__':raise SystemExit(main())
