"""A mask built from a comparison, `v &= -(E != 0);`, with the comparison held in a block-scoped word first.

`v &= -(*(u8 *)((s8 *)p + 0x50) != 0);` is the "keep v only when the flag is set" idiom (negating 0/1 gives 0/-1).
Written on one line, the compare, the negate and the `and` are one expression tree and KMC GCC 2.7.2 (`-O1 -g`) emits
the `and` with its operands the other way round from the game's, `and $s1,$s1,$v0` against `and $s1,$v0,$s1`: nothing
else differed, a 144-instruction N64 collision loop at 215 -> 0 (the polished form was
`{ s32 flag = *(u8 *)((s8 *)arg0 + 0x50) != 0; var_s1 &= -flag; }`). A word local for the tested value, declared in its
own block so it never lives past the statement, gives the flag its own pseudo, which changes the order the `and` is
built in (hypothesis from the output: the `and`'s commutative operands are put in register-number order, and the flag's
number is lower once it is a named pseudo; the judge decides).

A site is a statement `V &= -(E);` where `V` is a plain identifier and `E` is one comparison (`==`, `!=`, `<`, `>`, `<=`,
`>=`) with no `&&`, `||`, `?`, `,`, assignment or `++`/`--` at its top level. Each site gives a child, and with several
sites one more child has them all. The local is `flag`, with a suffix when the name is already used in the function.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'flag_local_negated_mask'
FAMILIES = (FAMILY,)
LIMIT = 6
_SITE = re.compile(rf'(?P<lhs>\b{IDENT})[ \t]*&=[ \t]*-[ \t]*\(')
_TOP_BANNED = re.compile(r'&&|\|\||\?|,|\+\+|--|(?<![=!<>])=(?!=)')
_COMPARE = re.compile(r'==|!=|<=|>=|<|>')


def _top_level(text):
    """`text` with everything inside brackets blanked."""
    depth, out = 0, []
    for ch in text:
        if ch in '([':
            depth += 1
            out.append(' ')
        elif ch in ')]':
            depth -= 1
            out.append(' ')
        else:
            out.append(ch if depth == 0 else ' ')
    return ''.join(out)


def _sites(part):
    found = []
    for hit in _SITE.finditer(part.clean, part.opening, part.end):
        opening = hit.end() - 1
        past = close(part.clean, opening, '(', ')')
        tail = re.match(r'[ \t]*;', part.clean[past:part.end]) if past else None
        if not tail:
            continue
        expression = part.clean[opening + 1:past - 1]
        top = _top_level(expression)
        if _TOP_BANNED.search(top) or len(_COMPARE.findall(top)) != 1:
            continue
        found.append((hit.start(), past + tail.end(), hit['lhs'], part.source[opening + 1:past - 1].strip()))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    if not sites:
        return []
    local, number = 'flag', 1
    while re.search(rf'\b{local}\b', part.clean):
        number += 1
        local = f'flag{number}'
    edits = [(start, end, '{ s32 %s = %s; %s &= -%s; }' % (local, expr, lhs, local)) for start, end, lhs, expr in sites]
    groups = [[one] for one in edits] + ([edits] if len(edits) > 1 else [])
    return [(FAMILY, edit(source, group)) for group in groups][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
