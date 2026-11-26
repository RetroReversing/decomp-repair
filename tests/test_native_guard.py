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


def _script():
    spec = importlib.util.spec_from_file_location("native_build_under_test", PACKAGE / "native_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_lists_what_has_no_build_of_its_source(tmp_path):
    build = _script()
    kernel, plain = build.KERNELS[0], "some_family"
    (tmp_path / f"{kernel}.pyx").write_text("def f(): pass\n")
    (tmp_path / f"{plain}.py").write_text("x = 1\n")
    (tmp_path / "permuter_gen.py").write_text("x = 1\n")  # stays interpreted
    assert build.missing(tmp_path) == [kernel]
    assert build.missing(tmp_path, everything=True) == [kernel, plain]
    _build(tmp_path, kernel, f"{kernel}.pyx")
    (tmp_path / "library.bin").write_bytes(b"")
    (tmp_path / build.MANIFEST).write_text(f"library.bin\n{plain} {build.digest_of(plain, tmp_path)}\n")
    assert build.missing(tmp_path, everything=True) == []
    (tmp_path / f"{plain}.py").write_text("x = 2\n")
    assert build.missing(tmp_path, everything=True) == [plain]
    (tmp_path / "library.bin").unlink()
    assert build.read_manifest(tmp_path) == ("", {})


def test_plain_modules_load_from_one_library_until_their_source_changes(tmp_path):
    if any(importlib.util.find_spec(name) is None for name in ("Cython", "setuptools")):
        pytest.skip("Cython is not installed")
    package = tmp_path / "somepackage"
    package.mkdir()
    shutil.copy(guard.__file__, package / "_native_guard.py")
    shutil.copy(PACKAGE / "native_build.py", package / "native_build.py")
    (package / "__init__.py").write_text("from . import _native_guard\n_native_guard.install(__name__, __path__[0])\n")
    (package / "one.py").write_text("def answer():\n    return 'one'\n")
    (package / "two.py").write_text("from . import one\n\ndef answer():\n    return one.answer() + ' and two'\n")

    def build(*arguments):
        return subprocess.run([sys.executable, str(package / "native_build.py"), "--package", str(package),
                               *arguments], capture_output=True, text=True, check=True).stdout

    def loaded():
        code = ("from somepackage import one, two\nimport os\n"
                "assert one.__file__.endswith('one.py') and two.__file__.endswith('two.py')\n"
                "print(two.answer())\n"
                "print(os.path.splitext(one.__spec__.origin)[1], os.path.splitext(two.__spec__.origin)[1])\n")
        return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
                              check=True).stdout.split("\n")[:2]

    if "Linked 2 modules" not in build("--all"):
        pytest.skip("no C compiler here")
    assert loaded() == ["one and two", ".bin .bin"]
    assert build("--all", "--missing") == "" and build("--all", "--list-missing") == ""
    (package / "one.py").write_text("def answer():\n    return 'changed'\n")
    assert loaded() == ["changed and two", ".py .bin"]  # the changed module from source, before any rebuild
    assert build("--all", "--list-missing").split() == ["one"]
    assert "Built 1 native" in build("--only", "one", "--missing", "--no-link")
    assert loaded()[1] == ".py .bin"
    assert "Linked 2 modules" in build("--all", "--missing", "--discard-objects")
    assert loaded() == ["changed and two", ".bin .bin"]
    assert len(list(package.glob("_compiled-*.bin"))) == 1 and not (package / "_objects").exists()
    build("--clean")
    assert loaded() == ["changed and two", ".py .py"]


def test_a_new_build_replaces_the_old_file_instead_of_writing_into_it(tmp_path):
    build = _script()
    package, work = tmp_path / "package", tmp_path / "work"
    package.mkdir()
    work.mkdir()
    old = _build(package, "mod")
    (work / old.name).write_bytes(b"the new build")
    with old.open("rb") as loaded:  # what a running process has mapped
        build.install_built(work / old.name, package, "abc")
        assert loaded.read() == b"not a shared library"
    assert old.read_bytes() == b"the new build"
    assert (package / (old.name + guard.STAMP)).read_text() == "abc\n"
    assert sorted(path.name for path in package.iterdir()) == sorted([old.name, old.name + guard.STAMP])


def test_missing_builds_once_and_then_has_nothing_to_do(tmp_path):
    if any(importlib.util.find_spec(name) is None for name in ("Cython", "setuptools")):
        pytest.skip("Cython is not installed")
    for name in ("native_build.py", "_scan.pyx"):
        shutil.copy(PACKAGE / name, tmp_path / name)

    def run(*arguments):
        return subprocess.run([sys.executable, str(tmp_path / "native_build.py"), "--package", str(tmp_path),
                               *arguments], capture_output=True, text=True, check=True).stdout

    if "Built 1 native" not in run("--missing"):
        pytest.skip("no C compiler here")
    built = next(path for path in tmp_path.iterdir() if path.suffix in (".so", ".pyd"))
    was = built.stat().st_mtime_ns
    assert run("--missing") == "" and run("--list-missing") == ""
    assert built.stat().st_mtime_ns == was
