"""Ignore compiled modules that were built from other source than the one installed now.

Python imports `<name>.<abi>.so` (or `.pyd`) in preference to `<name>.py` beside it. `native_build.py` writes such files
into an installed copy, and upgrading the library in place replaces the sources but leaves them: the old build then
answers for the new source (an old `_scan` kernel lacks the functions newer modules call: AttributeError), or silently
runs old code. So each build is stamped with the SHA-256 of the source it came from (`<file>.source`), and at import a
build whose stamp doesn't match is passed over: a module with a `.py` is imported from it, and a kernel with only a
`.pyx` is as if it had never been built, which every caller already handles with its plain Python twin.
"""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

STAMP = ".source"  # native_build.py writes <built file name> + STAMP; it runs by path, so it spells this itself


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


class _PassOverStaleBuilds(importlib.abc.MetaPathFinder):
    def __init__(self, package, stale):
        self.stale = {f"{package}.{module}": source for module, source in stale.items()}

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.stale:
            return None
        source = self.stale[fullname]
        if source is None:
            raise ModuleNotFoundError(f"{fullname} was built from older source: run native_build.py again", name=fullname)
        return importlib.util.spec_from_file_location(fullname, source)


def install(package, folder):
    """Put the stale builds of `package` out of the import system's reach; nothing to do when every build is current."""
    stale = stale_builds(folder)
    if stale:
        sys.meta_path.insert(0, _PassOverStaleBuilds(package, stale))
