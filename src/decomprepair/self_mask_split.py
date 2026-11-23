"""A variable masked inside the expression that overwrites it, written as the mask first and the expression after.

    v = ((v & m) << 16) / 76;      ->      v &= m;  v = (v << 16) / 76;

m2c folds the `and` into the expression it feeds. The game kept it as its own statement on the same variable, so the
masked value stays in the variable's register: the target had `and $s0,$s0,$v0; sll $v0,$s0,16`, where the folded form
puts the masked value in a temporary (`and $v0,$s0,$v0; sll $v0,$v0,16`) and so shifts the register choice of every
later use (two dead-zone filters in an input handler, 905 -> 885 in a 417-instruction function whose other rows
already matched).

Offered for a statement `V = (...(V & M)REST);` at the start of a statement (the previous token is `;`, `{` or `}`, so
a braceless `if (c) v = ...;` is never split into a conditional and an unconditional part), where `M` is a name or a
number. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'self_mask_split'
FAMILIES = (FAMILY,)
_STATEMENT = re.compile(
    rf'(?P<v>{IDENT})\s*=\s*(?P<open>\(*)\(\s*(?P=v)\s*&\s*(?P<m>{IDENT}|{NUMBER})\s*\)(?P<rest>[^;{{}}]*);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out, edits = [], []
    for hit in _STATEMENT.finditer(clean, part.opening + 1, part.end):
        before = clean[:hit.start()].rstrip()
        if before[-1:] not in (';', '{', '}'):
            continue
        # the outer parentheses the statement opened must close inside it
        depth = len(hit['open']) + hit['rest'].count('(') - hit['rest'].count(')')
        if depth != 0:
            continue
        v, m = hit['v'], hit['m']
        new = f"{v} &= {m}; {v} = {hit['open']}{v}{source[hit.start('rest'):hit.end('rest')]};"
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), new)])))
        edits.append((hit.start(), hit.end(), new))
    if len(edits) > 1:  # the filters of a function are all spelled one way: the whole set, as one child
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
