"""A two-arm test whose short arm only stores a constant, written with that arm first.

    if (x == 0) { next = f(mask); } else { done = 0; }          if (x != 0) { done = 0; } else { next = f(mask); }

m2c writes a switch arm that either computes the next state or finishes as `if (x == 0) { state = ...; } else { done =
0; }`, the order the game's own test had when the arm's branch is read from the other side. Where the exit stays in the
else arm GCC 2.7.2 lays the arm out as `beql x,$zero; <state>; j end; move done,$zero`; written with the exit first the
branch is `bnel x,$zero,end` with `move done,$zero` in its delay slot and the state's `j` falls out of the else arm:
a different layout of the same arm (the four closing arms of a state machine in a 417-instruction input handler,
1980 -> 840 together with the removal of m2c's dead tests and gotos; each arm alone is one row).

Offered for `if (C) { V = E; } else { W = K; }` (one assignment in each arm, K a literal, E not, C one comparison): one
child per test and one with all of them flipped, since the arms of one state machine are all spelled one way. A
candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close, negate

FAMILY = 'exit_arm_first'
FAMILIES = (FAMILY,)
_IF = re.compile(r'\bif\s*\(')
_ARM = re.compile(rf'\s*\{{\s*(?P<s>(?P<v>{IDENT})\s*=\s*(?P<e>[^;{{}}]+);)\s*\}}')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        shut = close(clean, hit.end() - 1)
        if not shut:
            continue
        flipped = negate(clean[hit.end():shut - 1])
        then = _ARM.match(clean, shut)
        if not flipped or not then:
            continue
        other = re.compile(r'\s*else\b').match(clean, then.end())
        otherwise = _ARM.match(clean, other.end()) if other else None
        if not otherwise or not re.fullmatch(NUMBER, otherwise['e'].strip()) or re.fullmatch(NUMBER, then['e'].strip()):
            continue
        text = f"if ({flipped}) {{ {otherwise['s']} }} else {{ {then['s']} }}"
        found.append((hit.start(), otherwise.end(), text))
    out = [(FAMILY, edit(source, [one])) for one in found]
    if len(found) > 1:
        out.append((FAMILY, edit(source, found)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
