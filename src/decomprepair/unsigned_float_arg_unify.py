"""An unsigned local converted to float through a signed double cast at some uses, written as the plain conversion at
every use, with the identical-arm guards a search left around a nearby call dropped (GCC 2.7.2, KMC, N64).

A search reaches for `(f32)(f64)(s32)y` when the target converts `y` with `cvt.d.w`/`cvt.s.d` and no `bgez` fix-up,
and for `(f32)(f64)y` where it has one. The game wrote `(f32)y` at every use of the unsigned `y`: GCC expands it as
the unsigned conversion (`cvt.d.w`, then `bgez` around the `+ 4294967296.0`), and cse folds the sign test away where it
knows `y` (a constant 0 along its path), which is where the target has no fix-up. The difference matters beyond the
fix-up: the signed form is one expression cse keeps and reuses at the next call (`mov.d` of the first call's double into
a saved float register, two calls later), the unsigned one is set twice (the conditional add) and cse never reuses it,
so each call converts afresh into `$f0`, as the target does. A search's identical-arm guard
(`if (table) { call(); } else { call(); }`) cut the cse path that knew the constant, so it goes with it.

Measured on a 556-instruction N64 split-screen setup routine (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): the casts
alone 4065 -> 4235, together with the guard dropped 4065 -> 2545 (62 -> 31 differing rows; every call's conversions and
float registers matched).

`variants` offers, for each unsigned scalar local (`u32`, `unsigned`, `unsigned int`, `unsigned long`) read through such a
cast at least once with `(s32)`: every `(f32)(f64)(s32)v`, `(f32)(f64)v`, `(f32)(double)v` and `(f32)(f64)(int)v` written
`(f32)v` together with every identical-arm guard the library's `identical_arm_collapse` drops, and the casts alone.
"""
import re

from . import identical_arm_collapse_repairs as collapse
from .integer_repair_support import IDENT, edit, view

FAMILY = 'unsigned_float_arg_unify'
FAMILIES = (FAMILY,)

_UNSIGNED = re.compile(rf'\b(?:u32|unsigned\s+int|unsigned\s+long|unsigned)\s+(?P<n>{IDENT})\s*;')
_FLOAT = r'(?:f32|float)'
_DOUBLE = r'(?:f64|double)'
_SIGNED = r'(?:s32|int|signed\s+int)'


def _casts(name):
    return re.compile(rf'\(\s*{_FLOAT}\s*\)\s*\(\s*{_DOUBLE}\s*\)\s*(?P<s>\(\s*{_SIGNED}\s*\)\s*)?{re.escape(name)}\b'
                      rf'(?!\s*(?:\[|\(|->|\.))')


def _collapse_all(source, name):
    for _ in range(8):
        children = collapse.variants(source, name)
        if not children:
            return source
        source = children[0][1]
    return source


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for decl in _UNSIGNED.finditer(clean, part.opening + 1, part.end):
        local = decl['n']
        if len(re.findall(rf'\b{re.escape(local)}\s*[;=,\[]', clean[part.opening + 1:decl.start()])):
            continue  # declared twice: a shadow
        hits = list(_casts(local).finditer(clean, decl.end(), part.end))
        if not hits or not any(h['s'] for h in hits):
            continue
        casts = edit(source, [(h.start(), h.end(), f'(f32){local}') for h in hits])
        both = _collapse_all(casts, name)
        for child in (both, casts):
            if child != source and (FAMILY, child) not in out:
                out.append((FAMILY, child))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
