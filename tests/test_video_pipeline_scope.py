import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_video2dsprite as video


class VideoPipelineScopeTests(unittest.TestCase):
    def test_key_material_warning_reports_applied_despill_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'frame.png'
            image=Image.new('RGBA',(48,48),(255,0,255,255))
            image.paste((255,200,0,255),(12,10,36,40))
            image.save(path)
            for requested,applied in (('auto','edge'),('all','all'),('edge','edge'),('off','off')):
                with self.subTest(requested=requested),patch.object(video.fm,'auto_interior_despill',
                    return_value={'reference_share':0.0,'clip_median_share':0.02,
                                  'interior_despill':False,'clip_sample_frames':[0]}):
                    plan=video._plan_clip([path],video.MatteSettings(key='magenta',
                        despill_mode=requested),None)
                    self.assertEqual(plan.despill_applied,applied)
                    warning=next(w for w in plan.warnings if 'applied despill mode:' in w)
                    self.assertIn('applied despill mode: '+applied,warning)
                    self.assertNotIn('subject owns',warning)
                    self.assertNotIn('stays off',warning)
                    self.assertEqual(plan.params.interior_despill,applied=='all')

    def test_shipped_local_imports_resolve_inside_this_project(self):
        scripts=[p for p in (ROOT/'skills').glob('*/scripts/*.py')]
        available={p.stem for p in scripts}
        for path in scripts:
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                names=[]
                if isinstance(node,ast.Import):names=[a.name for a in node.names]
                elif isinstance(node,ast.ImportFrom) and node.module:names=[node.module]
                for name in names:
                    if name.startswith('comfyui_forge_'):
                        self.assertIn(name.split('.')[0],available,(str(path),name))
        inputs=ROOT/'skills/comfyui-forge-generate2dsprite/scripts'
        self.assertEqual({p.name for p in inputs.glob('*.py')},{'comfyui_forge_master_still.py',
            'comfyui_forge_background_input.py','comfyui_forge_core.py','comfyui_forge_matte.py'})

    def test_video_commands_do_not_load_retired_engine_transports(self):
        parser=video.build_parser()
        self.assertEqual(parser.parse_args(['doctor']).func,video.cmd_doctor)
        self.assertEqual(parser.parse_args(['process','--video','fixture.mp4','--output-dir','new']).func,video.cmd_process)
        self.assertFalse(hasattr(video,'engine_module'))
        for command in ('package','verify','sample'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parser.parse_args([command])
        folder=ROOT/'skills/comfyui-forge-video2dsprite'
        for path in ('scripts/comfyui_forge_engine_export.py','scripts/comfyui_forge_validate_animation.py',
                     'references/runtime','references/packed-alpha-runtime.js',
                     'scripts/comfyui_forge_schema.py','references/schemas',
                     'scripts/comfyui_forge_animation_review.py'):
            target=folder/path
            self.assertFalse(target.is_file() or (target.is_dir() and any(target.iterdir())))

    def test_contract_validator_is_test_only_and_obsolete_preview_entry_is_absent(self):
        self.assertTrue((ROOT/'tests/contract_schema.py').is_file())
        self.assertFalse((ROOT/'shared/comfyui_forge_schema.py').exists())
        self.assertFalse((ROOT/'tools/comfyui_forge_export_preview.py').exists())


if __name__=='__main__':unittest.main()
