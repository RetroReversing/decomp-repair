"""decomprepair: targeted C rewrites that move a near-matching function closer to its original bytes.

Each repair module reads a function's C source and the compiled candidate's and target's code, and proposes
variant sources (typically a handful) that change one thing the byte difference points at: a literal, a local's
lifetime, an argument's carrier, a branch layout. A proposal is only a guess. This library never compiles or
judges: the caller compiles every variant with the game's own compiler and keeps one only when the bytes match
(decompdecomp's judge does this).

It is standalone on purpose: nothing here imports decompdecomp (`decompnet`), which tests/test_decomprepair.py
checks, so other decompilation tools can use it. It is MIPS-first: most evidence readers understand MIPS code;
other processors are planned (ROADMAP.md).

The modules are flat: `*_repairs` are the repair families, the rest are their shared readers (`csource` for C
text, `mips` and `mips_*` for MIPS code, `symbols` for symbol tables, `m2cfix` for m2c's output).
"""

from . import _native_guard as _guard

# before any other module of the package is imported: a compiled file left from an older version must not answer
_guard.install(__name__, __path__[0])
del _guard

import re as _re

# The families build thousands of patterns around a function's own names; Python keeps only 512 (plus 256 more in
# 3.12's second level), so a draft pass recompiled about one pattern in eight and spent 40% of its time in the regex
# compiler. Raising the limits (never lowering what the host set) cut a pass over real functions from 0.74 s to 0.43 s.
for _limit in ("_MAXCACHE", "_MAXCACHE2"):
    if isinstance(getattr(_re, _limit, None), int):
        setattr(_re, _limit, max(getattr(_re, _limit), 4096))
del _limit
