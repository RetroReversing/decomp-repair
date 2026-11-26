"""Every module native_build lists must get through Cython: one that doesn't is retried at every app start, and one
took over twenty minutes. Only the translation to C runs here (seconds); no C compiler is needed."""
import importlib.util
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "decomprepair"


def test_every_listed_module_translates_in_reasonable_time(tmp_path):
    if importlib.util.find_spec("Cython") is None:
        pytest.skip("Cython is not installed")
    spec = importlib.util.spec_from_file_location("native_build_listed", PACKAGE / "native_build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    def translate(name):
        done = subprocess.run([sys.executable, "-m", "cython", "-3", "-X", "annotation_typing=False", "-X",
                               "infer_types=False", str(PACKAGE / f"{name}.py"), "-o", str(tmp_path / f"{name}.c")],
                              capture_output=True, text=True, timeout=300)
        return None if done.returncode == 0 else f"{name}: {done.stderr[-300:]}"

    with ThreadPoolExecutor(4) as pool:
        assert [failure for failure in pool.map(translate, build.NATIVE) if failure] == []
