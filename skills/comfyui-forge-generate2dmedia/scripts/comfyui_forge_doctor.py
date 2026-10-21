#!/usr/bin/env python3
"""Check local ComfyUI readiness and report installed paths and versions."""
import argparse
import json
import hashlib
from pathlib import Path
import sys
import comfyui_forge_media

def runtime_identity():
    adapter = Path(comfyui_forge_media.__file__).resolve()
    manifest = adapter.parents[2] / ".comfyui-sprite-forge.install.json"
    installed = json.loads(manifest.read_text(encoding="utf-8-sig")) if manifest.is_file() else {}
    result = {"adapterPath": str(adapter), "adapterSha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
              "pythonPath": sys.executable, "installedProject": installed.get("project"),
              "manifestPath": str(manifest) if manifest.is_file() else None}
    project_adapter = (Path(installed["project"]) / "skills/comfyui-forge-generate2dmedia/scripts/comfyui_forge_media.py") if installed.get("project") else adapter
    result["projectAdapterPath"] = str(project_adapter)
    result["matchesProject"] = project_adapter.is_file() and hashlib.sha256(project_adapter.read_bytes()).hexdigest() == result["adapterSha256"]
    try:
        config = comfyui_forge_media.find_config()
        result.update(configPath=str(config), configSha256=hashlib.sha256(config.read_bytes()).hexdigest())
    except (OSError, ValueError, comfyui_forge_media.ComfyError) as exc:
        result["configError"] = str(exc)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save')
    parser.add_argument('--offline', action='store_true', help='report loaded paths and fingerprints without server access')
    args=parser.parse_args()
    try:
        readiness = {'status':'offline'} if args.offline else comfyui_forge_media.check()
        result={**readiness, 'routes':['local:comfyui'], 'imageGeneration':False}
        code=0 if result['status'] in ('ok','offline') else 1
    except (OSError, ValueError, KeyError, TypeError, OverflowError, comfyui_forge_media.ComfyError) as exc:
        result={'status':'error','routes':['local:comfyui'],'imageGeneration':False,'error':str(exc)}
        code=1
    result["runtime"] = runtime_identity()
    if args.save:
        path=Path(args.save); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return code

if __name__=='__main__':raise SystemExit(main())
