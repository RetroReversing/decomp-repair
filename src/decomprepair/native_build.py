#!/usr/bin/env python3
"""Compile the library with Cython, next to its sources (optional).

Two kinds of build, both from the sources beside them, so there is one source of truth:
- the typed kernels (KERNELS): each its own `<name>.<abi>.so`, seconds to build, many times faster per call;
- with `--all`, every other module unchanged, linked into one library (`_compiled-<hash>.<abi>.bin`, listed by
  `_compiled.<abi>.txt`) which `_native_guard.py` imports them from. One library, not a file each: the system's loader
  checks every file it maps, and 1,400 files took 19 s to import (214 s the first time, and 600 MB) where the one
  library takes half a second, less than interpreting. Each module's object file is kept (`_objects/`), so after an
  update only the changed modules are compiled again before relinking.

Without Cython or a C compiler nothing is built and nothing changes, and a module that no longer matches the source it
was built from is imported from its `.py`.

    native_build.py                    build the typed kernels
    native_build.py --all              and compile every other module into the one library (minutes)
    native_build.py --clean            remove everything built
    native_build.py --only a,b         build just those modules
    native_build.py --missing          build only what has no build of the current source, leaving the rest
    native_build.py --no-link          compile modules' object files without relinking the library (for batches)
    native_build.py --discard-objects  delete the object files once linked (a packaged copy never updates itself)
    native_build.py --list-missing     print what has no current build, one per line (with --all: modules too)
    native_build.py --package DIR      work on the decomprepair folder DIR (an installed copy: it must hold the
                                       .py files; needs Cython and setuptools, run it with the file's path so the
                                       package's own imports are not needed)

Nothing is ever written into a file in place: a process that is running keeps what it loaded, and one that is
starting never reads half of a build.
"""
import hashlib
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import sysconfig
import tempfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent  # --package DIR builds into another copy (an installed bundle)

# this Python's builds ("cpython-312-darwin"); _native_guard.py spells it and the manifest's name itself
TAG = importlib.machinery.EXTENSION_SUFFIXES[0].strip(".").rsplit(".", 1)[0]
MANIFEST = f"_compiled.{TAG}.txt"  # the library's file name, then "module digest" per line
OBJECTS = "_objects"

# Typed code (.pyx): faster per call by a large factor, and it compiles in seconds, so a bundle build always does it.
KERNELS = ["_scan"]

# Every other module is compiled unchanged (`--all`): a little faster each, so a new module joins without being listed.
# These stay interpreted: the package's own import and build code, which run before or while building, `__main__`
# (`python -m` runs a module's Python code, which a compiled one doesn't have), and the
# permuter's modules, which a subprocess loads by path as top-level modules and which rebuild functions from their
# `__code__` (permuter_capture), something a compiled function has none of.
INTERPRETED = ("__init__", "__main__", "_native_guard", "native_build")
INTERPRETED_PREFIXES = ("permuter",)


def plain_modules(package: Path | None = None) -> list[str]:
    names = (path.stem for path in Path(package or PACKAGE).glob("*.py"))
    return sorted(name for name in names if name not in INTERPRETED and not name.startswith(INTERPRETED_PREFIXES))


NATIVE = plain_modules()


def source_of(name: str, package: Path) -> Path:
    typed = package / f"{name}.pyx"
    return typed if typed.is_file() else package / f"{name}.py"


def digest_of(name: str, package: Path) -> str:
    return hashlib.sha256(source_of(name, package).read_bytes()).hexdigest()


def read_manifest(package: Path) -> tuple[str, dict[str, str]]:
    """(the library's file name, {module: digest of the source in it}); empty when there is no usable library."""
    try:
        lines = (package / MANIFEST).read_text(encoding="ascii").split("\n")
    except (OSError, UnicodeDecodeError):
        return "", {}
    if not lines[0] or not (package / lines[0]).is_file():
        return "", {}
    return lines[0], dict(line.split(" ", 1) for line in lines[1:] if " " in line)


def _kernel_current(name: str, package: Path) -> bool:
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        built = package / (name + suffix)
        if built.is_file():
            try:
                stamp = (package / (built.name + ".source")).read_text(encoding="ascii").strip()
                return stamp == digest_of(name, package)
            except (OSError, UnicodeDecodeError):
                return False
    return False


def current(name: str, package: Path | None = None, manifest: dict | None = None) -> bool:
    """True when this Python would import a build of `name` made from the source it has now."""
    package = Path(package or PACKAGE)
    if name in KERNELS:
        return _kernel_current(name, package)
    built = read_manifest(package)[1] if manifest is None else manifest
    return source_of(name, package).is_file() and built.get(name) == digest_of(name, package)


def missing(package: Path | None = None, everything: bool = False) -> list[str]:
    """The kernels (with `everything`, the plain modules too) that have a source here and no current build."""
    package = Path(package or PACKAGE)
    wanted = KERNELS + plain_modules(package) if everything else KERNELS
    manifest = read_manifest(package)[1]
    return [name for name in wanted if source_of(name, package).is_file() and not current(name, package, manifest)]


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # Windows holds what a process has loaded: the next build removes it
        pass


def _remove_files_per_module(names: list[str], package: Path) -> None:
    for name in names:
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            _remove(package / (name + suffix))
            _remove(package / (name + suffix + ".source"))


def clean(package: Path | None = None) -> None:
    package = Path(package or PACKAGE)
    _remove_files_per_module(KERNELS + plain_modules(package), package)
    _remove(package / MANIFEST)
    for library in package.glob(f"_compiled-*.{TAG}.bin"):
        _remove(library)
    shutil.rmtree(package / OBJECTS / TAG, ignore_errors=True)


def _c_file(name: str, package: Path, work: str, directives: dict):
    """Translate one module to C; returns the setuptools Extension that names the .c file."""
    from Cython.Build import cythonize
    from setuptools import Extension
    # no debug symbols, which Python's own flags ask for and nobody reads: a quarter off the compile time
    flags = [] if sys.platform == "win32" else ["-g0"]
    return cythonize([Extension(f"decomprepair.{name}", [str(source_of(name, package))], extra_compile_args=flags)],
                     build_dir=work, quiet=True, compiler_directives=directives)[0]


def _compiler():
    from setuptools._distutils.ccompiler import new_compiler
    from setuptools._distutils.sysconfig import customize_compiler
    compiler = new_compiler()
    customize_compiler(compiler)
    return compiler


def object_of(name: str, package: Path, digest: str) -> Path:
    return package / OBJECTS / TAG / f"{name}-{digest[:16]}{'.obj' if sys.platform == 'win32' else '.o'}"


def build_object(name: str, package: Path | None = None) -> int:
    """Compile one plain module's object file, unless it is there; a module that can't be compiled stays interpreted."""
    package = Path(package or PACKAGE)
    digest = digest_of(name, package)
    target = object_of(name, package, digest)
    if target.is_file():
        return 1
    # plain modules must behave as they do interpreted: annotations stay hints, and no guessed C types (Cython
    # spent over twenty minutes inferring them for expression_terms, which compiles in a second without)
    directives = {"language_level": "3", "annotation_typing": False, "infer_types": False}
    with tempfile.TemporaryDirectory(prefix="decomprepair-native-") as work:
        try:
            extension = _c_file(name, package, work, directives)
            built = _compiler().compile(extension.sources, output_dir=work,
                                        include_dirs=[sysconfig.get_path("include"), sysconfig.get_path("platinclude")],
                                        extra_postargs=extension.extra_compile_args)[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            arriving = target.with_name(f"{target.name}.{os.getpid()}.tmp")
            shutil.copyfile(built, arriving)
            os.replace(arriving, target)
        except (Exception, SystemExit) as error:  # no C compiler or headers, or code Cython can't translate
            print(f"{name}: not built, stays interpreted ({str(error)[:200]})")
            return 0
    return 1


def link(package: Path | None = None) -> int:
    """Link every current object file into the one library and list it; returns how many modules it holds."""
    package = Path(package or PACKAGE)
    digests = {name: digest_of(name, package) for name in plain_modules(package)}
    held = {name: digest for name, digest in digests.items() if object_of(name, package, digest).is_file()}
    library, listed = read_manifest(package)
    if held and held != listed:
        key = hashlib.sha256("".join(f"{name} {digest}\n" for name, digest in sorted(held.items())).encode()).hexdigest()
        library = f"_compiled-{key[:12]}.{TAG}.bin"  # its own name: the old one may be loaded
        objects = [str(object_of(name, package, digest)) for name, digest in sorted(held.items())]
        with tempfile.TemporaryDirectory(prefix="decomprepair-native-") as work:
            try:
                where = {"library_dirs": [str(Path(sys.base_prefix) / "libs")]} if sys.platform == "win32" else {}
                _compiler().link_shared_object(objects, str(Path(work) / library), build_temp=work,
                                               export_symbols=[f"PyInit_{name}" for name in sorted(held)], **where)
                arriving = package / f"{library}.{os.getpid()}.tmp"
                shutil.copyfile(Path(work) / library, arriving)
                os.replace(arriving, package / library)
            except (Exception, SystemExit) as error:
                print(f"the library was not linked, its modules stay as they were ({str(error)[:300]})")
                return 0
        arriving = package / f"{MANIFEST}.{os.getpid()}.tmp"
        arriving.write_text("".join([library + "\n"] + [f"{name} {digest}\n" for name, digest in sorted(held.items())]),
                            encoding="ascii")
        os.replace(arriving, package / MANIFEST)
    for old in package.glob(f"_compiled-*.{TAG}.bin"):
        if old.name != library:
            _remove(old)
    _remove_files_per_module(sorted(held), package)  # builds from when each module was a file of its own
    kept = {object_of(name, package, digest).name for name, digest in digests.items()}
    for path in (package / OBJECTS / TAG).glob("*"):
        if path.name not in kept and not path.name.endswith(".tmp"):
            _remove(path)
    return len(held)


def install_built(built: Path, package: Path, digest: str) -> None:
    """Move one built file and its stamp into `package`. Never written in place: a running process may have the old
    file mapped (macOS kills it when the bytes change under it) and a starting one must not load half of the new one."""
    destination = package / built.name
    stamp = package / (built.name + ".source")
    arriving = package / f"{built.name}.{os.getpid()}.tmp"  # no import suffix at its end
    try:
        arriving.write_bytes(built.read_bytes())
        stamp.unlink(missing_ok=True)  # an unstamped build is passed over, never trusted
        os.replace(arriving, destination)
        stamp.write_text(digest + "\n", encoding="ascii")
    finally:
        arriving.unlink(missing_ok=True)


def build_one(name: str, package: Path | None = None) -> int:
    """Compile one typed kernel into its own file."""
    from setuptools.dist import Distribution
    package = Path(package or PACKAGE)
    # stamped on the built file so the library passes over it once the source changes (_native_guard.py)
    digest = digest_of(name, package)
    with tempfile.TemporaryDirectory(prefix="decomprepair-native-") as work:
        try:
            extensions = [_c_file(name, package, work, {"language_level": "3"})]
            dist = Distribution({"ext_modules": extensions, "package_dir": {"": "src"}, "packages": ["decomprepair"]})
            command = dist.get_command_obj("build_ext")
            command.build_lib = work
            command.build_temp = str(Path(work) / "tmp")
            command.ensure_finalized()
            command.run()
        except (Exception, SystemExit) as error:  # no C compiler or headers, or code Cython can't translate
            print(f"{name}: not built, stays interpreted ({str(error)[:200]})")
            return 0
        count = 0
        for path in Path(work).rglob("decomprepair/*"):
            if path.suffix in (".so", ".pyd"):
                try:
                    install_built(path, package, digest)
                except OSError as error:  # Windows holds a loaded .pyd: the next build after it exits succeeds
                    print(f"{name}: not installed, stays as it was ({str(error)[:200]})")
                    continue
                count += 1
        return count


def _build(name: str, package: Path) -> int:
    return build_one(name, package) if name in KERNELS else build_object(name, package)


def main(argv: list[str]) -> int:
    global PACKAGE
    if "--package" in argv:
        PACKAGE = Path(argv[argv.index("--package") + 1]).resolve()
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None  # a few modules, to try it
    wanted = KERNELS + plain_modules(PACKAGE) if "--all" in argv or only else KERNELS
    names = [name for name in wanted if (only is None or name in only) and source_of(name, PACKAGE).is_file()]
    if "--list-missing" in argv:
        for name in missing(PACKAGE, everything="--all" in argv):
            print(name)
        return 0
    if "--clean" in argv:
        clean(PACKAGE)
        return 0
    if "--missing" in argv:
        manifest = read_manifest(PACKAGE)[1]
        names = [name for name in names if source_of(name, PACKAGE).is_file() and not current(name, PACKAGE, manifest)]
        if not names:
            return 0
    else:
        clean(PACKAGE)
    if any(importlib.util.find_spec(module) is None for module in ("Cython", "setuptools")):
        print("Cython or setuptools is unavailable: the library stays interpreted.")
        return 0
    jobs = int(os.environ.get("DECOMPREPAIR_NATIVE_JOBS", "4"))
    try:
        with ProcessPoolExecutor(jobs) as pool:
            built = sum(pool.map(_build, names, [PACKAGE] * len(names)))
    except BrokenProcessPool:  # a compiler worker was killed (memory pressure): finish what is missing one at a time
        built = sum(_build(name, PACKAGE) for name in names if name not in KERNELS or not current(name, PACKAGE))
    print(f"Built {built} native modules into {PACKAGE}.")
    if any(name not in KERNELS for name in names) and "--no-link" not in argv:
        print(f"Linked {link(PACKAGE)} modules into the library.")
        if "--discard-objects" in argv:
            shutil.rmtree(PACKAGE / OBJECTS, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
