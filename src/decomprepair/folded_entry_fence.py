"""A derived value whose constant entry value the compiler folds, computed from a fenced variable instead.

m2c writes the entry value of a loop's derived variable as its own constant expression: `var_a1 = 0 * 8;` beside
`var_v1 = 0;`. gcc 2.7.2 folds `0 * 8` to `0` and the later `var_v1` is the only register that holds the zero, so the
target's `sll $a1,$v1,3` after `move $v1,$zero` (the first iteration's derived value, computed from the live variable
like every later one) is never produced. Assigned first inside a one-shot fence, `do { var_v1 = 0; } while (0);`, the
variable's value is opaque to cse's constant folding and `var_a1 = var_v1 * 8;` keeps the shift (a pointer-table search
loop in a `gcc-2.7.2-kmc` game, 205 -> 0). Without the fence, `var_v1 = 0; var_a1 = var_v1 * 8;` folds again (230).
This is the other direction of `one_shot_unwrap`, which opens a fence.

Offered for two adjacent statements (either order) `A = K1 OP K2;` and `V = K;` where K is an integer literal equal to
K1 or K2 and OP is `*`, `<<`, `>>`, `&`, `|`, `+`, `-` or `/`: the pair becomes `do { V = K; } while (0);` then
`A = V OP K2;` (the variable stands where the equal literal was). One child per pair (`folded_entry_fence`). A
hypothesis, the judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view

FAMILY = 'folded_entry_fence'
FAMILIES = (FAMILY,)
LIMIT = 8
OPERATORS = r'\*|<<|>>|&|\||\+|-|/'
FOLDED = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<target>{IDENT})[ \t]*=[ \t]*(?P<left>{NUMBER})[ \t]*(?P<op>{OPERATORS})[ \t]*'
                    rf'(?P<right>{NUMBER})[ \t]*;')
ENTRY = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<name>{IDENT})[ \t]*=[ \t]*(?P<value>{NUMBER})[ \t]*;')


def _pair(clean, folded):
    """(the entry statement beside FOLDED, whether it follows it), or None."""
    after = ENTRY.match(clean, folded.end() + 1) if clean[folded.end():folded.end() + 1] == '\n' else None
    if after:
        return after, True
    if folded.start() > 0 and clean[folded.start() - 1] == '\n':
        before = ENTRY.match(clean, clean.rfind('\n', 0, folded.start() - 1) + 1)
        if before and before.end() == folded.start() - 1:
            return before, False
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for folded in FOLDED.finditer(clean, part.opening, part.end):
        pair = _pair(clean, folded)
        if not pair:
            continue
        entry, follows = pair
        if entry['name'] == folded['target'] or entry['name'] in (folded['left'], folded['right']):
            continue
        value = integer(entry['value'])
        if integer(folded['left']) == value:
            derived = f'{entry["name"]} {folded["op"]} {folded["right"]}'
        elif integer(folded['right']) == value:
            derived = f'{folded["left"]} {folded["op"]} {entry["name"]}'
        else:
            continue
        start, end = (folded.start(), entry.end()) if follows else (entry.start(), folded.end())
        indent = entry['indent']
        text = (f'{indent}do {{ {entry["name"]} = {entry["value"]}; }} while (0);\n'
                f'{folded["indent"]}{folded["target"]} = {derived};')
        found.append((start, end, text))
    return [(FAMILY, edit(source, [one])) for one in found[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
