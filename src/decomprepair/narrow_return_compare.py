"""A callee's narrow return type and an offset compare, written as the int the game compared.

Two things in a KMC GCC 2.7.2 N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`) were each worse alone and exact
together (2420 -> 2270 with both; 2520 and 2470 with one):

- the callee `randomIntBelow` was declared `volatile short randomIntBelow();` in the candidate (an earlier search wrote
  the width, and `volatile` kept the result from being reused), and its result went through `sll`/`sra` before the
  arithmetic on it; every caller of it in the game reads an `int` (`callers.py`), and the target has no extension.
  Declared `s32` the call is plain; alone that scored 100 worse, because
- the guard `if (3 < (temp_a0 + 1))` of the same statement run (a byte loaded, compared, passed to the call as
  `temp_a0 - 1`) put the `+ 1` in a register before the compare (`addiu`, `slti ...,4`), where the target compares the
  byte itself (`slti $v0, $a0, 3`). Written `temp_a0 >= 3` it is the target's compare, and alone it scored 50 worse (the
  extension after the call then stood out).

`variants` offers, for each unprototyped narrow callee declaration in the candidate (`short`, `volatile short`, `s16`,
`s8`, `u8`, `u16`, `char`, `unsigned char`, `unsigned short` before `name();`) of a function the body calls, `s32` in
its place, and for each signed local compared with a constant after an addition (`K < (x + c)`, `(x + c) > K`,
`K <= (x + c)`, `(x - c) < K` and their mirrors) the compare of the local alone (`x >= K - c + 1`); the declaration
and the compares together come first as one child (the combination is what scores), then each alone. At most 6."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'narrow_return_compare'
FAMILIES = (FAMILY,)
LIMIT = 6
_NARROW = r'(?:volatile\s+)?(?:unsigned\s+(?:short|char)|signed\s+(?:short|char)|short|char|[su](?:8|16))'
_DECL = re.compile(rf'(?m)^(?P<lead>[ \t]*)(?P<type>{_NARROW})(?P<gap>[ \t]+\**[ \t]*)(?P<name>{IDENT})\s*\(\s*\)\s*;')
_SIGNED = {'s8', 's16', 's32', 'int', 'short', 'char', 'signed char', 'signed short', 'signed int', 'long'}
_LOCAL = re.compile(rf'(?m)^[ \t]*(?:register[ \t]+)?(?P<type>(?:signed[ \t]+)?(?:char|short|int|long)|s8|s16|s32)[ \t]+(?P<names>{IDENT}(?:[ \t]*,[ \t]*{IDENT})*)[ \t]*;')
_OPS = {'<': '>', '>': '<', '<=': '>=', '>=': '<='}


def _signed_locals(part):
    out = set()
    for hit in _LOCAL.finditer(part.clean, part.opening + 1, part.end):
        if ' '.join(hit['type'].split()) in _SIGNED:
            out |= set(re.findall(IDENT, hit['names']))
    return out


def _folds(part, source, signed):
    """[(start, end, replacement)] of the offset compares of signed locals."""
    out = []
    pattern = re.compile(rf'(?<![\w)])(?P<k>-?{NUMBER})\s*(?P<op>[<>]=?)\s*\(\s*(?P<x>{IDENT})\s*(?P<sign>[+-])\s*(?P<c>{NUMBER})\s*\)'
                         rf'|\(\s*(?P<x2>{IDENT})\s*(?P<sign2>[+-])\s*(?P<c2>{NUMBER})\s*\)\s*(?P<op2>[<>]=?)\s*(?P<k2>-?{NUMBER})')
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        if hit['x']:
            x, op, k, c, sign = hit['x'], _OPS[hit['op']], int(hit['k'], 0), int(hit['c'], 0), hit['sign']
        else:
            x, op, k, c, sign = hit['x2'], hit['op2'], int(hit['k2'], 0), int(hit['c2'], 0), hit['sign2']
        if x not in signed:
            continue
        shift = k - (c if sign == '+' else -c)  # x + c OP k  ->  x OP (k - c)
        if op == '>':  # an integer compare: `x > n` is `x >= n + 1`
            op, shift = '>=', shift + 1
        out.append((hit.start(), hit.end(), f'{x} {op} {shift}'))
    return out


def variants(source, name):
    """Proposals: the narrow callee declarations widened and the offset compares folded, together first, then each."""
    part = view(source, name)
    if not part:
        return []
    called = set(re.findall(rf'(?<![\w.>])({IDENT})\s*\(', part.clean[part.opening:part.end]))
    declarations = [(hit.start('type'), hit.end('type'), 's32') for hit in _DECL.finditer(part.clean, 0, part.opening)
                    if hit['name'] in called and hit['name'] != name]
    folds = _folds(part, source, _signed_locals(part))
    out = []
    if declarations and folds:
        out.append(edit(source, declarations + folds))
    if declarations:
        out.append(edit(source, declarations))
        out += [edit(source, [one]) for one in declarations] if len(declarations) > 1 else []
    if folds:
        out.append(edit(source, folds))
    return [('narrow_return_compare', text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 55}  # the registry: no caller wiring (registry.py)
