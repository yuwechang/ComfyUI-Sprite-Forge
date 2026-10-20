#!/usr/bin/env python3
"""Run only the supported offline release suites; no server, GPU or network."""
from pathlib import Path
import sys
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    subprocess.run([sys.executable, '-B', str(ROOT/'tools/comfyui_forge_vendor_sync.py'), '--check', '--strict'], check=True)
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/comfyui_forge_check_entrypoints.py')],check=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
