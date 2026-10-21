"""Fixed resolution choices and consistent capped source-time arithmetic."""
from pathlib import Path
import copy
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/comfyui-forge-video2dsprite/scripts'))
import comfyui_forge_animation_spec as spec
import comfyui_forge_contracts as contracts
import comfyui_forge_frame_rules as rules
import comfyui_forge_media as media
from test_comfyui_media import GRAPH, CONFIG


class SetupPolicyTests(unittest.TestCase):
    def test_numbered_fixed_tiers_independent_of_final_size_rate_and_envelope(self):
        expected=[[512,512],[768,768],[1024,1024]]
        for cell in ('64x64','128x128','256x256','512x512'):
            for fps in (4,8,16):
                with self.subTest(cell=cell,fps=fps):
                    p=spec.plan(cell=cell,fps=fps,mode='oneshot-return',envelope='1.3,1',ratio='3:4')
                    self.assertEqual([o['size'] for o in p['sourceOptions'].values()],expected)
                    self.assertEqual([o['selectionNumber'] for o in p['sourceOptions'].values()],[1,2,3])
                    self.assertEqual(p['recommendedTier'],'balanced')
                    self.assertEqual(p['sourceOptions']['balanced']['requestedSeconds'],3)
                    self.assertEqual(p['sourceOptions']['balanced']['fps'],24)

    def test_source_time_factor_and_cap_do_not_follow_output_fps(self):
        for factor in (2,'5/2',3):
            for fps in (4,8,16):
                p=spec.plan(duration=2,fps=fps,source_factor=factor,mode='oneshot-return')
                self.assertEqual(p['sourceOptions']['balanced']['requestedSeconds'],2*float(spec.positive(factor)))
        p=spec.plan(duration=8,source_factor=3,mode='oneshot-return')
        source=p['sourceOptions']['balanced']
        self.assertEqual(source['requestedSeconds'],15)
        self.assertEqual(source['frameCount'],345)
        self.assertEqual(source['actualSeconds'],14.375)
        self.assertIn('source_duration_capped_at_15_seconds_candidate_count_requires_review',p['warnings'])
        for factor in (1,4):
            with self.assertRaises(ValueError):spec.plan(source_factor=factor)
        with self.assertRaises(ValueError):spec.plan(source_duration='15.01')

    def test_source_ceiling_agrees_between_planner_contract_and_submitter(self):
        for seconds in (0.1,1,3,6,14,14.4,14.9,15):
            with self.subTest(seconds=seconds):
                p=spec.plan(source_duration=seconds,mode='oneshot-return')
                source=p['sourceOptions']['balanced']
                checked=contracts.source(source)
                graph,actual=media.prepare(CONFIG,GRAPH,prompt='fixture',first='first.png',last=None,
                                           width=768,height=768,duration=seconds)
                self.assertEqual(graph['4']['inputs']['length'],source['frameCount'])
                self.assertEqual(checked['frameCount'],source['frameCount'])
                self.assertEqual(actual,source['actualSeconds'])
                self.assertLessEqual(actual,15)
                self.assertEqual(source['frameCount']%17,5)
        with self.assertRaises(ValueError):rules.frame_count(15.01)
        with self.assertRaises(ValueError):contracts.source({'size':[768,768],'requestedSeconds':16})
        with self.assertRaises(media.ComfyError):media.prepare(CONFIG,GRAPH,prompt='fixture',first='first.png',last=None,
                                                        width=768,height=768,duration=16)
        invalid=copy.deepcopy(spec.plan(source_duration=15,mode='oneshot-return')['sourceOptions']['balanced'])
        invalid.update(frameCount=362,actualSeconds=362/24)
        with self.assertRaises(ValueError):contracts.source(invalid)

    def test_custom_source_dimensions_stay_within_range(self):
        for dimensions in ('480x512','512x1056'):
            with self.assertRaisesRegex(ValueError,'between 512 and 1024'):
                spec.plan(source_size=dimensions)
        self.assertEqual(spec.plan(source_size='640x768')['sourceOptions']['custom']['size'],[640,768])


if __name__=='__main__':unittest.main()
