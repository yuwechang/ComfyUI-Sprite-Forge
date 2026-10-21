import ast
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_video2dsprite as video


class VideoPipelineScopeTests(unittest.TestCase):
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
        self.assertEqual(parser.parse_args(['process','--video','fixture.mp4','--output-dir','new',
                                          '--skip-sampling']).func,video.cmd_process)
        self.assertFalse(hasattr(video,'engine_module'))
        for command in ('package','verify'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parser.parse_args([command])
        folder=ROOT/'skills/comfyui-forge-video2dsprite'
        for path in ('scripts/comfyui_forge_engine_export.py','scripts/comfyui_forge_validate_animation.py',
                     'references/runtime','references/packed-alpha-runtime.js',
                     'scripts/comfyui_forge_schema.py','references/schemas'):
            target=folder/path
            self.assertFalse(target.is_file() or (target.is_dir() and any(target.iterdir())))

    def test_contract_validator_is_test_only_and_obsolete_preview_entry_is_absent(self):
        self.assertTrue((ROOT/'tests/contract_schema.py').is_file())
        self.assertFalse((ROOT/'shared/comfyui_forge_schema.py').exists())
        self.assertFalse((ROOT/'tools/comfyui_forge_export_preview.py').exists())


if __name__=='__main__':unittest.main()
