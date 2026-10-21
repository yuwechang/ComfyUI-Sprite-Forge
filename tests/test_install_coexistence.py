import hashlib
import contextlib
import io
import json
from unittest.mock import patch
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fork_installer',ROOT/'tools/comfyui_forge_install_skills.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
ORIGINAL=('codeart2d','generate2dmap','generate2dmedia','generate2dsprite','video2dsprite')
CORE=('generate2dmedia','generate2dsprite','video2dsprite')

def snapshot(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

class CoexistenceTests(unittest.TestCase):
    def test_install_and_update_preserve_original(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills';dest.mkdir()
            for name in ORIGINAL:
                folder=dest/name;folder.mkdir();(folder/'SKILL.md').write_text('Original '+name,encoding='utf-8')
            (dest/'.agent-sprite-forge.install.json').write_text('{"original":true}',encoding='utf-8')
            (dest/'unrelated').mkdir();(dest/'unrelated/SKILL.md').write_text('Unrelated',encoding='utf-8')
            before=snapshot(dest)
            skills=installer.source_skills(ROOT/'skills',None)
            installer.apply(ROOT/'skills',dest,skills,base/'backup-first')
            installer.apply(ROOT/'skills',dest,skills,base/'backup-update')
            after=snapshot(dest)
            for path,digest in before.items():self.assertEqual(after[path],digest,path)
            self.assertTrue((dest/'.comfyui-sprite-forge.install.json').is_file())
            self.assertFalse(installer.drift(ROOT/'skills',dest,skills))

    def test_core_update_archives_previously_managed_optional_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills'
            core=installer.source_skills(ROOT/'skills',None)
            installer.apply(ROOT/'skills',dest,core,base/'first')
            # Simulate a previous five-skill fork installation without shipping the retired code.
            manifest_path=dest/installer.MANIFEST
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            for name in ('codeart2d','generate2dmap'):
                legacy='comfyui-forge-'+name
                folder=dest/legacy;folder.mkdir();(folder/'SKILL.md').write_text('legacy fork fixture',encoding='utf-8')
                manifest['skills'].append(legacy)
            manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
            core=installer.source_skills(ROOT/'skills',None)
            self.assertEqual(len(core),3)
            installer.apply(ROOT/'skills',dest,core,base/'second')
            for name in ('codeart2d','generate2dmap'):
                self.assertFalse((dest/('comfyui-forge-'+name)).exists())
                self.assertTrue((base/'second'/('comfyui-forge-'+name)/'SKILL.md').is_file())
            self.assertFalse(installer.drift(ROOT/'skills',dest,core))

    def test_unmanaged_legacy_names_are_not_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills';dest.mkdir()
            for name in ('codeart2d','generate2dmap'):
                folder=dest/('comfyui-forge-'+name);folder.mkdir()
                (folder/'SKILL.md').write_text('unmanaged user files',encoding='utf-8')
            before=snapshot(dest)
            core=installer.source_skills(ROOT/'skills',None)
            installer.apply(ROOT/'skills',dest,core,base/'backup')
            after=snapshot(dest)
            for path,digest in before.items():self.assertEqual(after[path],digest)

    def test_retired_modules_cannot_be_selected_or_reinstalled(self):
        self.assertEqual(set(installer.source_skills(ROOT/'skills',None)),{'comfyui-forge-'+n for n in CORE})
        self.assertEqual({p.name for p in (ROOT/'skills').iterdir() if p.is_dir()}, {'comfyui-forge-'+n for n in CORE})
        for name in ('codeart2d','generate2dmap'):
            with self.assertRaises(installer.InstallError):installer.source_skills(ROOT/'skills',['comfyui-forge-'+name])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            installer.build_parser().parse_args(['--check','--host','codex','--include-extras'])

    def test_failed_migration_restores_retired_and_original_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);dest=base/'skills';dest.mkdir()
            (dest/'generate2dmap').mkdir();(dest/'generate2dmap/SKILL.md').write_text('original',encoding='utf-8')
            legacy='comfyui-forge-generate2dmap'
            (dest/legacy).mkdir();(dest/legacy/'SKILL.md').write_text('legacy',encoding='utf-8')
            (dest/installer.MANIFEST).write_text(json.dumps({'skills':[legacy],'files':[]}),encoding='utf-8')
            before=snapshot(dest)
            with patch.object(installer,'_write_manifest',side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):installer.apply(ROOT/'skills',dest,installer.source_skills(ROOT/'skills',None),base/'backup')
            self.assertEqual(snapshot(dest),before)

    def test_unnamespaced_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'video2dsprite').mkdir();(root/'video2dsprite/SKILL.md').write_text('x')
            with self.assertRaises(installer.InstallError):installer.source_skills(root,None)

    def test_frontmatter_and_sibling_routes_are_namespaced(self):
        for name in CORE:
            folder=ROOT/'skills'/('comfyui-forge-'+name)
            self.assertIn('name: comfyui-forge-'+name,(folder/'SKILL.md').read_text(encoding='utf-8'))
        video=(ROOT/'skills/comfyui-forge-video2dsprite/scripts/comfyui_forge_sprite_set.py').read_text(encoding='utf-8')
        self.assertIn('"comfyui-forge-generate2dmedia"',video)

if __name__=='__main__':unittest.main()
