"""A compiled module left from other source is passed over: an upgrade in place once left an old `_scan` kernel behind,
and every family that called a newer kernel function failed with AttributeError."""
import hashlib
import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from decomprepair import _native_guard as guard

SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]
PACKAGE = Path(guard.__file__).parent


def _build(folder, module, source_name=None):
    """A stand-in for a compiled file (not loadable on purpose), stamped as built from `source_name` when given."""
    built = folder / (module + SUFFIX)
    built.write_bytes(b"not a shared library")
    if source_name:
        digest = hashlib.sha256((folder / source_name).read_bytes()).hexdigest()
        (folder / (built.name + guard.STAMP)).write_text(digest + "\n", encoding="ascii")
    return built


def test_only_a_build_of_the_current_source_counts(tmp_path):
    (tmp_path / "plain.py").write_text("x = 1\n")
    (tmp_path / "kernel.pyx").write_text("def f(): pass\n")
    _build(tmp_path, "plain", "plain.py")
    _build(tmp_path, "kernel", "kernel.pyx")
    assert guard.stale_builds(tmp_path) == {}
    (tmp_path / "plain.py").write_text("x = 2\n")  # the upgrade: new sources beside the old builds
    (tmp_path / "kernel.pyx").write_text("def f(): pass\ndef g(): pass\n")
    assert guard.stale_builds(tmp_path) == {"plain": str(tmp_path / "plain.py"), "kernel": None}


def test_an_unstamped_build_and_one_with_no_source_are_stale(tmp_path):
    (tmp_path / "plain.py").write_text("x = 1\n")
    _build(tmp_path, "plain")  # built before builds were stamped
    _build(tmp_path, "gone")
    assert guard.stale_builds(tmp_path) == {"plain": str(tmp_path / "plain.py"), "gone": None}


def test_a_package_with_stale_builds_imports_its_source_and_reports_the_kernel_missing(tmp_path):
    package = tmp_path / "somepackage"
    package.mkdir()
    shutil.copy(guard.__file__, package / "_native_guard.py")
    (package / "__init__.py").write_text("from . import _native_guard\n_native_guard.install(__name__, __path__[0])\n")
    (package / "mod.py").write_text("answer = 'from source'\n")
    (package / "_kern.pyx").write_text("def f(): pass\n")
    _build(package, "mod")
    _build(package, "_kern")
    code = ("from somepackage import mod\nprint(mod.answer)\n"
            "try:\n    from somepackage import _kern\nexcept ImportError:\n    print('no kernel')\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert out.split("\n")[:2] == ["from source", "no kernel"]


def test_native_build_stamps_what_it_builds(tmp_path):
    if any(importlib.util.find_spec(name) is None for name in ("Cython", "setuptools")):
        pytest.skip("Cython is not installed")
    for name in ("native_build.py", "_scan.pyx"):
        shutil.copy(PACKAGE / name, tmp_path / name)
    out = subprocess.run([sys.executable, str(tmp_path / "native_build.py"), "--package", str(tmp_path)],
                         capture_output=True, text=True, check=True).stdout
    if "Built 1 native" not in out:
        pytest.skip("no C compiler here")
    assert guard.stale_builds(tmp_path) == {}
    with open(tmp_path / "_scan.pyx", "a", encoding="utf-8") as source:
        source.write("\n# changed\n")
    assert guard.stale_builds(tmp_path) == {"_scan": None}
