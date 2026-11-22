"""A halfword built from two bytes, written as two statements on a halfword local that is passed on.

`id = (u16)(p[0] | (p[7] << 8)); if (id != 0) { t = f(); ...` against `u16 id = p[0]; id |= p[7] << 8; ... f(id)`.
On KMC GCC 2.7.2 (N64) the one-statement form narrows the whole expression to a halfword, and `combine` sees the
`zero_extend` that the test and the call argument need as redundant (the value is a single set whose bits are all
known), so the `andi $a0, $v1, 0xffff` the target keeps never appears: the test reads `$v1` and the argument register
is loaded later. Written as two sets of a halfword local, `combine` can no longer trust the earlier value (hypothesis:
the single-set condition in `nonzero_bits`; not confirmed in the compiler's source, the measured fact is below), the
extension is emitted at the use, and the compare reads the register the call then takes as its argument.
One sound-engine function (a 62-instruction note starter, 105 -> 0) needed three edits together: the local declared
`u16`, the two-statement build, and the callee's argument (m2c dropped it from an unprototyped `f()`). Each alone
left the score at 105, which is why a one-edit-at-a-time search never reached it.

Children, for a statement `X = A | (B << n);` (the `(u16)` cast and m2c's `__repair_inline(...)` wrapper are looked
through, and `(B << n) | A` is read the same way): the split with the unshifted operand first and with the shifted one
first; each with `X` declared `u16`; and each of those with `X` added as the argument of the call that follows in an
`if (X)` / `if (X != 0)` guard when the source declares its callee with no parameter list. The combination is a
child of its own. Only MIPS, and a function with no `volatile`. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'halfword_byte_pair_split'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_STATEMENT = re.compile(rf'(?<=[;{{}}])(\s*)({_ID})\s*=\s*([^;{{}}=]+);')
_WIDE = r'(?:unsigned\s+)?(?:s16|u16|s32|u32|int|long|short)|unsigned'


def _balanced(text):
    depth = 0
    for c in text:
        depth += (c in '([') - (c in ')]')
        if depth < 0:
            return False
    return depth == 0


def _strip(text):
    """`(u16)(...)`, `__repair_inline(...)` and plain parentheses around an expression, removed."""
    text = text.strip()
    while True:
        m = (re.fullmatch(r'\(\s*(?:u16|unsigned short)\s*\)\s*\((.*)\)', text, re.S)
             or re.fullmatch(r'__repair_inline\s*\((.*)\)', text, re.S)
             or re.fullmatch(r'\((.*)\)', text, re.S))
        if not m or not _balanced(m[1]):
            return text
        text = m[1].strip()


def _pair(rhs):
    """(low, high, shift) of `A | (B << n)` in either order, else None."""
    expr = _strip(rhs)
    depth, cuts = 0, []
    for i, c in enumerate(expr):
        depth += (c in '([') - (c in ')]')
        if depth == 0 and c == '|' and expr[i - 1:i] != '|' and expr[i + 1:i + 2] not in ('|', '='):
            cuts.append(i)
    if len(cuts) != 1 or re.search(r'[?:&]|\|\|', expr):
        return None
    left, right = expr[:cuts[0]].strip(), expr[cuts[0] + 1:].strip()
    shifted = []
    for part in (left, right):
        inner = _strip(part)
        at = [m.start() for m in re.finditer('<<', inner) if _balanced(inner[:m.start()])]
        shifted.append((inner[:at[0]].strip(), inner[at[0] + 2:].strip()) if len(at) == 1 else None)
    if shifted[0] and shifted[1]:
        return None
    if shifted[1]:
        return left, shifted[1][0], shifted[1][1]
    if shifted[0]:
        return right, shifted[0][0], shifted[0][1]
    return None


def _apply(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    out = []
    for hit in _STATEMENT.finditer(clean, opening, span[1]):
        var = hit[2]
        parts = _pair(source[hit.start(3):hit.end(3)])
        if not parts or re.search(rf'\b{var}\b', ' '.join(parts)) or not all(parts):
            continue
        low, high, shift = parts
        indent = hit[1].split('\n')[-1]
        decl = re.search(rf'(?<![\w])({_WIDE})\s+{var}\s*;', clean[opening:hit.start()])
        narrow = []
        if decl and decl[1] != 'u16':
            narrow = [(opening + decl.start(1), opening + decl.end(1), 'u16')]
        guard = re.compile(rf'\s*if\s*\(\s*{var}\s*(?:!=\s*0\s*)?\)\s*\{{\s*(?:{_ID}\s*=\s*)?({_ID})\s*\(\s*\)')
        call = guard.match(clean, hit.end())
        argument = []
        if call and re.search(rf'(?<![\w.>])[A-Za-z_][\w\s\*]*\b{call[1]}\s*\(\s*\)\s*;', clean[:span[0]]):
            argument = [(call.end() - 1, call.end(), var + ')')]
        for first, second in ((low, f'({high}) << {shift}'), (f'({high}) << {shift}', low)):
            edits = [(hit.start(2), hit.end(), f'{var} = {first};\n{indent}{var} |= {second};')]
            for extra in ([], narrow, argument, narrow + argument):
                out.append(_apply(source, edits + extra))
    seen, unique = set(), []
    for text in out:
        if text != source and text not in seen:
            seen.add(text)
            unique.append((FAMILY, text))
    return unique


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
