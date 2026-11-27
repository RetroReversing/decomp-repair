"""A loop compared with a literal a local is set to just afterwards, written with the local set before the loop.

    while (*e < 0x80000000) e += 2;          start = 0x80000000;
    start = 0x80000000;              ->      while (*e < start) e += 2;

The target keeps the constant in the local's register across the search (`bltz` on entry because cse knows its value,
`sltu` against the register inside the loop). With a table scan after a boot memory check: 1280 -> 0 (SN64 GCC 2.8.1
-O2). The local must not be named between the loop and its assignment, and its signedness must keep the comparison's
meaning: unsigned for a constant above 0x7FFFFFFF, signed otherwise. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'constant_bound_local'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|[1-9]\d*)[uU]?'
_ASSIGN = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<name>{IDENT})\s*=\s*(?P<value>{_NUMBER})\s*;')
_LOOP = re.compile(r'(?<![\w])while\s*\(')
_SIGNED = ('s32', 'int', 'signed int')
_UNSIGNED = ('u32', 'unsigned int')
LIMIT = 8


def _value(text):
    return int(text.rstrip('uU'), 0)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    kinds = {decl['name']: ' '.join(decl['type'].split()) for decl in locals_for(part)}
    out = []
    for loop in _LOOP.finditer(clean, part.opening, part.end):
        before = clean[:loop.start()].rstrip()
        if not before.endswith((';', '{', '}')):
            continue  # a `do ... while`, or the body of an unbraced `if`
        paren = loop.end() - 1
        after = close(clean, paren, '(', ')')
        if not after:
            continue
        rest = len(clean) - len(clean[after:].lstrip())
        if clean.startswith('{', rest):
            stop = close(clean, rest, '{', '}')
        else:
            stop = clean.find(';', rest) + 1
        if not stop:
            continue
        for bound in re.finditer(rf'(?:<=|>=|==|!=|(?<![<>-])[<>])\s*(?P<value>{_NUMBER})\s*(?=\)|&&|\|\|)',
                                 clean[paren:after]):
            value = _value(bound['value'])
            for assign in _ASSIGN.finditer(clean, stop, part.end):
                local = assign['name']
                allowed = _UNSIGNED if value > 0x7FFFFFFF else _SIGNED
                if _value(assign['value']) != value or kinds.get(local) not in allowed:
                    continue
                between = clean[loop.start():assign.start('name')]
                # the assignment is reached from the loop with no block opened or closed on the way
                tail = clean[stop:assign.start('name')]
                if re.search(rf'\b{local}\b', between) or '{' in tail or '}' in tail:
                    continue
                changes = [(loop.start(), loop.start(), f'{local} = {assign["value"]};\n    '),
                           (paren + bound.start('value'), paren + bound.end('value'), local),
                           (assign.start(), assign.end(), '')]
                text = edit(source, changes)
                if (FAMILY, text) not in out:
                    out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
