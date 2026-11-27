"""A parameter the function never reads, put back between the ones it does.

An original signature can carry a parameter the body ignores. m2c drops it, and every later argument moves one place:
`f(a, b, f32 x, f32 z)` takes `z` in `$a3` where the target of `f(a, b, f32 x, f32 y, f32 z)` loads it from the
caller's stack (`lwc1 $f8, 0x10($sp)` against `mtc1 $a3, $f8`). Only the signature changes, so each child inserts one
unused `f32` or `s32` after one of the parameters.

Measured on one N64 function (KMC GCC 2.7.2 `-O1`, 372 instructions): 200 -> 0 with an `f32` before the last
parameter, where no other family's child moved the score."""
import re

from .integer_repair_support import edit, view

FAMILIES = ('unused_parameter_insert',)
FAMILY = FAMILIES[0]
UNUSED = 'unused_parameter'
LIMIT = 12


def _definition(clean, name, opening):
    """The span between the parentheses of `name`'s definition, whose body opens at `opening`."""
    found = None
    for match in re.finditer(r'\b' + re.escape(name) + r'\s*\(', clean[:opening]):
        found = match
    if not found:
        return None
    close = clean.rfind(')', found.end(), opening)
    return (found.end(), close) if close >= 0 else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(rf'\b{UNUSED}\b', source):
        return []
    span = _definition(part.clean, name, part.opening)
    if not span:
        return []
    start, end = span
    parameters = part.clean[start:end]
    # a parenthesis is a function pointer, `...` a variadic list: neither splits on commas
    if '(' in parameters or '...' in parameters or parameters.strip() in ('', 'void'):
        return []
    ends, at = [], start
    for parameter in parameters.split(','):
        at += len(parameter)
        ends.append(at)
        at += 1
    result = []
    # nearest the end first: a moved stack argument shows on the last parameters
    for place in reversed(ends):
        for kind in ('f32', 's32'):
            if kind == 'f32' and not re.search(r'\bf32\b', source + header):
                continue
            result.append((FAMILY, edit(source, [(place, place, f', {kind} {UNUSED}')])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 2000}
