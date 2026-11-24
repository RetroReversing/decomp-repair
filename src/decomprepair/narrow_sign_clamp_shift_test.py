"""A clamp whose lower bound tests a narrow sign (`if ((s16) v < 0) v = 0; else if (v >= K) v = M;`) written as a wide sum
tested by a shift: `{ s32 sum; sum = E; F = sum; if ((sum << 16) >= 0) { v = sum; if (v >= K) v = M; } else { v = 0; } }`.

KMC GCC 2.7.2 (`-O2`, N64) folds a `(s16) v < 0` test of a sum whose operands it can bound (a `lbu` byte plus a
`sll 16; sra 24` signed byte: 23 known sign bits) into a test of the whole register (`bgez $v1`), because combine's
`num_sign_bit_copies` sees the sum through the extension (combine.c, the SIGN_EXTEND and ASHIFT cases of
`simplify_comparison`). A target that keeps `sll $v1, $v1, 16; bltz $v1` tested the sum shifted by hand: `(sum << 16)
< 0` is a sign-bit comparison of an ASHIFT, which simplify_comparison turns into `(sum & 0x8000) != 0`, no branch insn
matches that, so the shift and the `bltz` stay. The clamped value is a second variable copied from the sum (`move
$v0, $v1` before the store, the copy back in the branch's delay slot), and the positive arm falls through: written as
`if ((sum << 16) >= 0) { v = sum; ... } else { v = 0; }`. On a 1315-instruction sound-sequence interpreter's
pan-offset command, 6125 -> 5910 with the two together (the shift test with the old polarity alone was 6215).

Rewrites `V = E; [F = V;] if (((s16) V) < 0) { V = 0; } else if (V >= K) { V = M; }` (braces optional, `>`/`>=`).
The sum is declared in a block of its own so no declaration moves. The sum is named `sum` (`sum2`, ... when the
function already uses the name).
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'narrow_sign_clamp_shift_test'
FAMILIES = (FAMILY,)
LIMIT = 4

_STMT = r'\s*\{?\s*%s\s*=\s*([^;{}]+);\s*\}?'


def _fresh(text):
    for name in ('sum', 'sum2', 'sum3', 'clampSum'):
        if not re.search(rf'\b{name}\b', text):
            return name
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    sum_name = _fresh(body)
    if not sum_name:
        return []
    pattern = re.compile(
        rf'(?m)^([ \t]*)({IDENT})\s*=\s*([^;{{}}]+);[ \t]*\n'
        rf'(?:([ \t]*)([^;{{}}\n]+?)\s*=\s*\2\s*;[ \t]*\n)?'
        rf'[ \t]*if\s*\(\s*\(?\s*\(\s*s16\s*\)\s*\2\s*\)?\s*<\s*0\s*\)'
        + (_STMT % r'\2') +
        r'\s*else\s+if\s*\(\s*\2\s*(>=|>)\s*([^)]+?)\s*\)'
        + (_STMT % r'\2'))
    out = []
    for found in pattern.finditer(body):
        indent, var, expr = found.group(1), found.group(2), found.group(3).strip()
        store = found.group(5)
        zero = found.group(6).strip()
        compare, bound, cap = found.group(7), found.group(8).strip(), found.group(9).strip()
        if var == sum_name or re.search(rf'\b{var}\b', expr):
            continue
        if not re.search(rf'(?m)^[ \t]*(?:u16|s16|u32|s32|int|unsigned short|short)[ \t]+{var}[ \t]*;', body):
            continue  # a byte local is never negative as `(s16)`: the shift test would be another program
        if store and not re.match(r'\s*\*\s*\(\s*\(\s*[us]16\s*\*', store):
            continue  # the raw sum stored into a wider cell would keep bits the halfword drops
        inner = indent + '  '
        lines = [f'{indent}{{', f'{indent}s32 {sum_name};', f'{indent}{sum_name} = {expr};']
        if store:
            lines.append(f'{indent}{store.strip()} = {sum_name};')
        lines += [f'{indent}if (({sum_name} << 16) >= 0)', f'{indent}{{', f'{inner}{var} = {sum_name};',
                  f'{inner}if ({var} {compare} {bound})', f'{inner}{{', f'{inner}  {var} = {cap};', f'{inner}}}',
                  f'{indent}}}', f'{indent}else', f'{indent}{{', f'{inner}{var} = {zero};', f'{indent}}}', f'{indent}}}']
        start, end = lo + found.start(), lo + found.end()
        if source[start:end] != clean[start:end]:
            continue  # a comment or string inside the match: leave it alone
        out.append((FAMILY, source[:start] + '\n'.join(lines) + '\n' + source[end:].lstrip('\n')))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
