"""A halfword or byte stepped and tested in one expression: `(s16)--p->timer == 0` as the shift or the two statements.

KMC GCC 2.7.2 (`-O1`, N64) reads `(s16) --p->timer == 0` of a `u16` field as a zero extension (`andi $v0,$v0,0xffff`),
but the target tests the stored value with `sll $v0,$v0,0x10`. The same test written as `p->timer--; if ((s16)
p->timer == 0)` or as `(--p->timer << 16) == 0` gives the shift (200 -> 0 on a 215-instruction N64 camera state
machine, where none of the library's other children moved the score).

A proposal rewrites an `if (...)` condition that is one `(s16)`/`(s8)` cast of a prefix `++`/`--` compared with zero,
into the shift form, and, where the `if` starts a statement, into the step followed by the cast test.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrow_step_test'
FAMILIES = (FAMILY,)
LIMIT = 8

_SHIFT = {'s16': 16, 'u16': 16, 's8': 24, 'u8': 24}
_PLACE = r'\*?\s*[A-Za-z_]\w*(?:\s*(?:->|\.)\s*\w+|\s*\[[^\[\]]*\])*'
_CONDITION = re.compile(r'\s*\(\s*(?P<kind>s16|u16|s8|u8)\s*\)\s*(?P<open>\(\s*)?(?P<step>\+\+|--)\s*(?P<place>' + _PLACE
                        + r')\s*(?(open)\))\s*(?P<test>(?:==|!=|<=?|>=?)\s*0)?\s*')


def variants(source, name):
    """Proposals for each narrow step-and-test condition."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for guard in re.finditer(r'\bif\s*\(', clean[span[0]:span[1]]):
        at = span[0] + guard.start()
        paren = span[0] + guard.end() - 1
        end = close(clean, paren, '(', ')')
        if not end:
            continue
        found = _CONDITION.fullmatch(source[paren + 1:end - 1])
        if not found:
            continue
        kind, step, place = found['kind'], found['step'], found['place'].strip()
        test = found['test'] or '!= 0'
        if test.rstrip(' 0') in ('==', '!='):
            out.append((FAMILY, source[:paren + 1] + f'({step}{place} << {_SHIFT[kind]}) {test}' + source[end - 1:]))
        if clean[:at].rstrip()[-1:] in ('{', '}', ';'):
            indent = source[source.rfind('\n', 0, at) + 1:at]
            gap = '\n' + indent if not indent.strip() else ' '
            out.append((FAMILY, source[:at] + f'{place}{step};{gap}' + source[at:paren + 1] + f'({kind}){place} {test}'
                        + source[end - 1:]))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
