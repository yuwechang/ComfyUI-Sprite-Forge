"""Install into a temporary mock Codex home, without touching the real installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from test_comfyui_media import GRAPH, CONFIG

ROOT=Path(__file__).resolve().parents[1]

class PortableInstallTests(unittest.TestCase):
    def run_tool(self,*args,**kwargs):
        env=dict(os.environ)
        env.pop('COMFYUI_FORGE_CONFIG',None)
        env['PYTHONUTF8']='1';env['PYTHONDONTWRITEBYTECODE']='1'
        return subprocess.run([sys.executable,*map(str,args)],capture_output=True,text=True,encoding='utf-8',env=env,**kwargs)

    def test_installed_tool_discovers_private_config_without_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills';dest.mkdir()
            # Preserve a real-looking upstream namespace and its manifest.
            upstream=dest/'video2dsprite';upstream.mkdir();(upstream/'SKILL.md').write_text('upstream untouched',encoding='utf-8')
            (dest/'.agent-sprite-forge.install.json').write_text('original manifest',encoding='utf-8')
            # Synthetic graph with fake node types: tests only, no model/workflow distribution.
            (base/'workflow.json').write_text(json.dumps(GRAPH),encoding='utf-8')
            cfg=json.loads(json.dumps(CONFIG))
            cfg['workflow']='workflow.json';config=base/'my-config.json';config.write_text(json.dumps(cfg),encoding='utf-8')
            installed=self.run_tool(ROOT/'tools/comfyui_forge_install_skills.py','--apply','--dest',dest,'--config',config)
            self.assertEqual(installed.returncode,0,installed.stderr)
            receipt=json.loads((dest/'.comfyui-sprite-forge.install.json').read_text(encoding='utf-8'))
            self.assertEqual(Path(receipt['comfyuiConfig']),config)
            self.assertEqual(len(receipt['skills']),3)
            self.assertEqual((upstream/'SKILL.md').read_text(encoding='utf-8'),'upstream untouched')
            self.assertEqual((dest/'.agent-sprite-forge.install.json').read_text(encoding='utf-8'),'original manifest')
            Image.new('RGB',(96,64),'magenta').save(base/'input.png')
            (base/'prompt.txt').write_text('one runner, locked camera',encoding='utf-8')
            dry=self.run_tool(dest/'comfyui-forge-generate2dmedia/scripts/comfyui_forge_route_media.py','video','--reference',base/'input.png',
                '--prompt-file',base/'prompt.txt','--out-dir',base/'never-created','--dry-run',cwd=base)
            self.assertEqual(dry.returncode,0,dry.stderr)
            result=json.loads(dry.stdout);self.assertEqual(result['route'],'local:comfyui')
            self.assertAlmostEqual(result['durationUsed'],73/24)
            self.assertFalse((base/'never-created').exists())
            planned=self.run_tool(dest/'comfyui-forge-video2dsprite/scripts/comfyui_forge_animation_spec.py','plan','--mode','loop','--config',config,cwd=base)
            self.assertEqual(planned.returncode,0,planned.stderr)
            self.assertEqual(json.loads(planned.stdout)['sourceOptions']['balanced']['size'],[640,640])
            self.assertEqual(json.loads(planned.stdout)['sourceOptions']['balanced']['frameCount'],73)

            self.assertEqual(self.run_tool(ROOT/'tools/comfyui_forge_install_skills.py','--check','--dest',dest).returncode,0)
            config.rename(base/'moved-config.json')
            missing=self.run_tool(dest/'comfyui-forge-generate2dmedia/scripts/comfyui_forge_route_media.py','resolve','--kind','video')
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('moved or removed',missing.stderr)

    def test_missing_config_fails_before_creating_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills'
            result=self.run_tool(ROOT/'tools/comfyui_forge_install_skills.py','--apply','--dest',dest,'--config',base/'missing.json')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(dest.exists())

    def test_ui_workflow_is_refused_before_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);(base/'workflow.json').write_text('{"nodes":[]}',encoding='utf-8')
            (base/'config.json').write_text(json.dumps({'url':'http://127.0.0.1:8188','workflow':'workflow.json'}),encoding='utf-8')
            result=self.run_tool(ROOT/'tools/comfyui_forge_install_skills.py','--apply','--dest',base/'skills','--config',base/'config.json')
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((base/'skills').exists())

if __name__=='__main__':unittest.main()
