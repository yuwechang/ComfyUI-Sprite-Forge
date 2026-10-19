#!/usr/bin/env python3
"""Run only the supported offline release suites; no server, GPU or network."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    suite=unittest.TestSuite()
    for pattern in ('test_comfyui_media.py','test_comfyui_only.py','test_install_coexistence.py','test_portable_install.py','test_export_preview.py','test_animation_spec.py','test_delivery.py'):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
