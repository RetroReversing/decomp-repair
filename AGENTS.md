# AGENTS.md

How to work in this repository (decomprepair: targeted C rewrites for near-matching decompiled functions; see README.md).

## Loops over text or numbers are typed Cython kernels

New code that walks text character by character, or steps through offsets and indexes (a bracket or brace matcher, a
statement or block scanner, a depth counter, an index walk) is written as a **typed kernel in `src/decomprepair/_scan.pyx`**
(or a new `<name>.pyx` listed in `KERNELS` in `native_build.py`), not as a Python loop. C integers over the string's own
characters (`Py_ssize_t`, `Py_UCS4`, `str` arguments, `boundscheck=False`) measured 10x to 70x faster per call than the
same loop in Python (`c_scan.close` 142 us -> 2 us, `pattern_repairs.close` 244 us -> 29 us, `c_scan.own_loop_statements`
433 us -> 42 us on a 120-block function).

Every kernel follows the pattern the existing ones use:

1. **A plain-Python twin stays.** The Python function keeps its name with a leading underscore (`_close`) and is the
   fallback: the module imports the kernel when it is built (`try: from . import _scan`) and rebinds the public name, and
   hands the twin back to the kernel (`_scan.python_close = _close`) for what the kernel doesn't take.
   A module's *own* private matcher (`_close` in a repair module) keeps its loop as `_python_close`, binds `_close =
   _python_close`, and replaces `_close` with a small wrapper over the shared kernel when `_scan` imports
   (`_scan.close_if` / `_scan.close_every`, which answer `NotImplemented` for arguments the loop reads its own way). New
   modules need no matcher of their own: use `c_scan` or `pattern_repairs.close`.
2. **Odd arguments go back to the twin.** A negative offset, an offset past the text, brackets longer than one character,
   an empty word: whatever the Python version treats in its own way (indexing from the end, raising `IndexError`) is
   delegated to it, so every answer and every exception stays the twin's.
3. **An equivalence test.** `tests/test_scan_kernels.py` compares the kernel with its twin on 20,000 random texts built
   from the characters the scan cares about (include multi-byte characters, newlines and odd offsets), comparing exceptions
   too, and checks the library uses the kernel when it is built. The test skips when the kernel is not built.
4. **Measure it.** A new kernel's pull request says its per-call time against the Python version on a real function's
   text. Use CPU time (`time.process_time`), not wall time: the machine is often busy.
5. **It builds in seconds and is on by default.** `python src/decomprepair/native_build.py` builds `KERNELS`; the bundles
   of decompdecomp run it. Run the test suite with the kernel built and with it removed (`native_build.py --clean`).

## What stays Python

Typing helps only where the time is a loop over characters or numbers. Code whose time is regex matching, `str` methods,
dict/set/tuple work or dataclass construction stays Python: compiling those modules unchanged (`native_build.py --all`,
146 modules) measured about 3% on a draft pass for about an hour of compiling, so it is not the default. Before adding
anything for speed, profile a real function (`cProfile` over the declared repairs on m2c C from a real decomp, not a
synthetic one): the large wins here came from quadratic scans, regexes that backtrack exponentially, repeated analyses of
the same source and caches, all fixed in plain Python.

## Other conventions

- A repair module declares `REPAIR` and needs no wiring in the app (README.md, "Adding a repair module").
- The library never imports `decompnet`, and never compiles or judges: it only proposes C.
- `uv run ruff check src tests` passes. The tests run with `pytest -n 4`; two of them
  (`tests/test_library.py`, `tests/test_registry.py`) race over probe files the registry tests write into the package,
  so they can fail under `-n` and pass when run alone.
- A change goes on a branch named `<type>/<short-name>` (`feat`, `fix`, `perf`, `docs`, `test`, `chore`) through a pull
  request; releases are tagged by the release workflow, and decompdecomp's `library-pin.yml` follows them.
