import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/comfyui-forge-video2dsprite/scripts'
sys.path.insert(0, str(SCRIPTS))
import comfyui_forge_animation_spec as spec
from comfyui_forge_frame_rules import frame_count


class SpecificationTests(unittest.TestCase):
    def test_first_use_does_not_assume_loop_or_write_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            result = spec.show(path)
            self.assertEqual(result['status'], 'first_use')
            self.assertEqual(result['proposal']['final']['status'], 'needs_confirmation')
            self.assertFalse(path.exists())

    def test_initial_three_tiers_and_actual_duration(self):
        p = spec.plan(mode='loop')
        self.assertEqual(p['final']['frameCount'], 8)
        self.assertEqual([s['size'] for s in p['sourceOptions'].values()], [[512, 512], [768, 768], [1024, 1024]])
        self.assertEqual(p['sourceOptions']['balanced']['frameCount'], 73)
        self.assertAlmostEqual(p['sourceOptions']['balanced']['actualSeconds'], 73 / 24)

    def test_custom_final_keeps_fixed_tiers_and_drives_candidate_time(self):
        p = spec.plan(cell='64x64', duration=2, fps=12, mode='oneshot')
        self.assertEqual(p['final']['frameCount'], 24)
        self.assertEqual([s['size'] for s in p['sourceOptions'].values()], [[512, 512], [768, 768], [1024, 1024]])
        self.assertEqual(p['sourceOptions']['balanced']['requestedSeconds'], 6)
        self.assertEqual(p['sourceOptions']['balanced']['frameCount'], 158)

    def test_fractional_final_count_needs_confirmation_and_cannot_be_saved(self):
        p = spec.plan(duration='.8', fps=12, mode='loop')
        self.assertEqual(p['final']['status'], 'needs_confirmation')
        self.assertEqual([x['frameCount'] for x in p['final']['frameCountAlternatives']], [9, 10])
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            spec.save(p, 'balanced', Path(temp) / 'settings.json', True)

    def test_rational_final_timing_survives_save_and_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            spec.save(spec.plan(duration='1/3', fps=24, mode='oneshot'), 'balanced', path, True)
            self.assertEqual(spec.show(path)['status'], 'ask_reuse')
            self.assertEqual(spec.show(path)['settings']['final']['durationRational'], '1/3')

    def test_alignment_and_envelope_and_aspect(self):
        p = spec.plan(cell='65x96', ratio='3:4', envelope='1.2,1', mode='loop')
        for source in p['sourceOptions'].values():
            self.assertTrue(all(v % 32 == 0 for v in source['size']))
            self.assertGreaterEqual(source['size'][0], 65 * 4 * 1.2)
            self.assertGreaterEqual(source['size'][1], 96 * 4)

    def test_non_aligned_custom_rejected_with_suggestion(self):
        with self.assertRaisesRegex(ValueError, 'suggested canvas'):
            spec.plan(source_size='640x641', mode='loop')

    def test_small_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least the final'):
            spec.plan(cell='256x256', source_size='128x128', mode='loop')

    def test_configured_minimum_preserves_fixed_tiers_with_fixed_cadence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            path.write_text(json.dumps({'fps': 24,
                                        'planning': {'minimum_source_size': [512, 512]}}))
            p = spec.plan(cell='32x32', config=path, mode='loop')
            self.assertEqual([o['size'] for o in p['sourceOptions'].values()], [[512, 512], [768, 768], [1024, 1024]])
            self.assertEqual(p['sourceOptions']['balanced']['frameCount'], 73)
            self.assertEqual(p['sourceOptions']['balanced']['actualSeconds'], 73 / 24)

    def test_save_requires_confirmation_and_explicit_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json';p = spec.plan(mode='loop')
            with self.assertRaises(ValueError):spec.save(p, 'balanced', path)
            self.assertFalse(path.exists())
            spec.save(p, 'performance', path, True)
            self.assertEqual(spec.show(path)['settings']['source']['size'], [512, 512])
            with self.assertRaises(ValueError):spec.save(p, 'quality', path, True)
            spec.save(p, 'quality', path, True, True)
            self.assertEqual(spec.show(path)['settings']['source']['size'], [1024, 1024])

    def test_changed_workflow_requires_reconfirmation_and_stale_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);cfg = root / 'config.json';dest = root / 'settings.json'
            cfg.write_text('{"fps":24}')
            p = spec.plan(config=cfg, mode='loop');spec.save(p, 'balanced', dest, True)
            cfg.write_text('{"fps":12}')
            with self.assertRaises(ValueError):spec.save(p, 'balanced', dest, True, True)
            # Previous source fps and changed config fps must be reconciled, not silently reused.
            self.assertEqual(spec.show(dest)['status'], 'reconfirm')
            self.assertIn('fps must be 24', spec.show(dest)['reason'])

    def test_source_fps_override_requires_matching_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json';path.write_text('{"fps":24}')
            with self.assertRaisesRegex(ValueError, 'fps differs'):
                spec.plan(config=path, source_fps=12, mode='loop')

    def test_frame_expression_minimum_and_boundaries(self):
        for duration in [.001, .2, 1, 2, 3, 3.1875, 6]:
            expected = max(5, round(duration * 24))
            expected += (5 - expected % 17) % 17
            self.assertEqual(frame_count(duration, 24), expected)
        for bad in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):frame_count(bad, 24)

    def test_omitted_config_cadence_uses_fixed_expression(self):
        from comfyui_forge_frame_rules import from_config
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json';path.write_text('{"fps":24}')
            source = spec.plan(config=path, mode='loop')['sourceOptions']['balanced']
            self.assertEqual(source['frameCount'], from_config({'fps':24},3))
            self.assertEqual(source['frameCount'],73)

    def test_submitter_uses_exactly_same_frame_rules_as_recommendations(self):
        from test_comfyui_media import GRAPH, CONFIG
        import comfyui_forge_media
        for duration in [.001, 2, 3, 6]:
            graph, actual = comfyui_forge_media.prepare(CONFIG, GRAPH, prompt='test', first='first.png', last=None,
                                                  width=640, height=640, duration=duration)
            self.assertEqual(graph['4']['inputs']['length'], frame_count(duration, 24))
            self.assertEqual(actual, frame_count(duration, 24) / 24)


if __name__ == '__main__':
    unittest.main()
