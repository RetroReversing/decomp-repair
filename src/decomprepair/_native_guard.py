"""Ignore compiled modules that were built from other source than the one installed now.

Python imports `<name>.<abi>.so` (or `.pyd`) in preference to `<name>.py` beside it. `native_build.py` writes such files
into an installed copy, and upgrading the library in place replaces the sources but leaves them: the old build then
answers for the new source (an old `_scan` kernel lacks the functions newer modules call: AttributeError), or silently
runs old code. So each build is stamped with the SHA-256 of the source it came from (`<file>.source`), and at import a
build whose stamp doesn't match is passed over: a module with a `.py` is imported from it, and a kernel with only a
`.pyx` is as if it had never been built, which every caller already handles with its plain Python twin.

The plain modules are compiled into one library instead of a file each, which the import system can't find by itself:
this also imports them from it, each only while the digest the library lists for it matches its `.py`.
"""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

STAMP = ".source"  # native_build.py writes <built file name> + STAMP; it runs by path, so it spells this itself
# native_build.py's MANIFEST: the one library's file name, then "module digest" per line
MANIFEST = f"_compiled.{importlib.machinery.EXTENSION_SUFFIXES[0].strip('.').rsplit('.', 1)[0]}.txt"


def _digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _current(folder, built, module):
    """True when `built` carries the stamp of the source `module` has in `folder` now."""
    source = os.path.join(folder, module + ".pyx")
    if not os.path.isfile(source):
        source = os.path.join(folder, module + ".py")
    try:
        with open(os.path.join(folder, built + STAMP), encoding="ascii") as handle:
            return handle.read().strip() == _digest(source)
    except (OSError, UnicodeDecodeError):  # no stamp (an older build), no source, or neither can be read
        return False


def stale_builds(folder):
    """{module: its `.py` path, or None when it has none} for each compiled file in `folder` this Python would import
    that was not built from the current source."""
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    stale = {}
    try:
        names = os.listdir(folder)
    except OSError:  # a package imported from an archive has no folder to hold a build either
        return stale
    for built in names:
        if built.endswith(suffixes):
            module = built.split(".", 1)[0]
            if not _current(folder, built, module):
                plain = os.path.join(folder, module + ".py")
                stale[module] = plain if os.path.isfile(plain) else None
    return stale


def read_library(folder):
    """(the library's path, {module: digest}) as native_build.py listed it; (None, {}) when there is no library."""
    try:
        with open(os.path.join(folder, MANIFEST), encoding="ascii") as handle:
            lines = handle.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return None, {}
    library = os.path.join(folder, lines[0])
    if not lines[0] or not os.path.isfile(library):
        return None, {}
    return library, dict(line.split(" ", 1) for line in lines[1:] if " " in line)


class _FromLibrary(importlib.machinery.ExtensionFileLoader):
    """Load one module out of the library. Its `__file__` stays its `.py`, as interpreted: code and tests that read a
    module's own source, or look beside it, must not find a binary (`__spec__.origin` is the library)."""

    def __init__(self, name, library, source):
        super().__init__(name, library)
        self.source = source

    def exec_module(self, module):
        module.__file__ = self.source
        super().exec_module(module)


class _CompiledOrSource(importlib.abc.MetaPathFinder):
    """A module from the library while it matches its source; past a stale file of its own, its source."""

    def __init__(self, package, folder, stale, library, built):
        self.prefix, self.folder, self.library = package + ".", folder, library
        self.built, self.stale = built, stale

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.prefix):
            return None
        module = fullname[len(self.prefix):]
        if module in self.built:
            source = os.path.join(self.folder, module + ".py")
            try:
                matches = _digest(source) == self.built[module]
            except OSError:
                matches = False
            if matches:
                loader = _FromLibrary(fullname, self.library, source)
                return importlib.util.spec_from_file_location(fullname, self.library, loader=loader)
        if module not in self.stale:
            return None
        source = self.stale[module]
        if source is None:
            raise ModuleNotFoundError(f"{fullname} was built from older source: run native_build.py again", name=fullname)
        return importlib.util.spec_from_file_location(fullname, source)


def install(package, folder):
    """Import `package`'s modules from its compiled library, and keep stale builds out of the import system's reach;
    nothing to do when there is neither."""
    stale = stale_builds(folder)
    library, built = read_library(folder)
    if stale or built:
        sys.meta_path.insert(0, _CompiledOrSource(package, folder, stale, library, built))
