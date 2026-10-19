"""The fork must never replace original Sprite Forge skills or its manifest."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fork_installer',ROOT/'tools/install_skills.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
ORIGINAL=('codeart2d','generate2dmap','generate2dmedia','generate2dsprite','video2dsprite')

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

    def test_unnamespaced_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'video2dsprite').mkdir();(root/'video2dsprite/SKILL.md').write_text('x')
            with self.assertRaises(installer.InstallError):installer.source_skills(root,None)

    def test_frontmatter_and_sibling_routes_are_namespaced(self):
        for name in ORIGINAL:
            folder=ROOT/'skills'/('comfyui-forge-'+name)
            self.assertIn('name: comfyui-forge-'+name,(folder/'SKILL.md').read_text(encoding='utf-8'))
        video=(ROOT/'skills/comfyui-forge-video2dsprite/scripts/sprite_set.py').read_text(encoding='utf-8')
        self.assertIn('"comfyui-forge-generate2dmedia"',video)

if __name__=='__main__':unittest.main()
