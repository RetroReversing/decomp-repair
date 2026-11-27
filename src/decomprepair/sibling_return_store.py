"""A literal field store one pointer of a record type gets, written for another one that is returned.

A cache lookup marks the block it hands back on both of its paths: the freshly set up block (`fresh->state = 2;`) and
the block it found (`hit->state = 2; return hit;`). A draft or a source adapted from a look-alike often has only the
first, and the whole difference is then two instructions the target has and ours lacks
(`addiu $v0, $zero, 2; sw $v0, 8($a2)` before the jump to the epilogue). No rewrite that moves or respells the
existing statements can add them. One N64 function (103 instructions, `gcc-2.7.2-kmc -O2`) went 200 -> 0 with
exactly this store.

For every `return p;` of a pointer to a named type, and every `q->field = literal;` where `q` is another pointer of
that type, one child writes `p->field = literal;` just before the return (bracing an unbraced `if`/`else` body).
A return whose block already stores that field of `p` is left alone. This changes what the program does, so it is
only a hypothesis until the caller's judge says the bytes agree; it never compiles or judges.
"""
import re

from .integer_repair_support import IDENT, NUMBER, view

FAMILY = 'sibling_return_store'
FAMILIES = (FAMILY,)
LIMIT = 32
WORDS = {'return', 'else', 'sizeof', 'goto', 'case'}
DECLARATION = re.compile(rf'(?:(?<=[;{{}}(,])|^)\s*(?:(?:const|volatile|register|static)\s+)*'
                         rf'(?P<type>(?:struct\s+|union\s+)?{IDENT})\b(?P<rest>\s*\*\s*{IDENT}'
                         rf'(?:\s*=\s*[^,;(){{}}]+)?(?:\s*,\s*\*\s*{IDENT}(?:\s*=\s*[^,;(){{}}]+)?)*)\s*(?=[;,)])')
POINTER = re.compile(rf'(?:^|,)\s*\*\s*({IDENT})')
STORE = re.compile(rf'(?<![\w.>])(?P<base>{IDENT})\s*->\s*(?P<field>{IDENT}(?:\.{IDENT})*)\s*=\s*'
                   rf'(?P<value>-?\s*{NUMBER}|NULL)\s*;')
RETURN = re.compile(rf'\breturn\s+(?P<name>{IDENT})\s*;')


def _pointers(text):
    """Each single-level pointer declared in `text` (parameters and locals) and the type it points to; a name declared
    with two types is left out."""
    found = {}
    for hit in DECLARATION.finditer(text):
        kind = ' '.join(hit['type'].split())
        if kind in WORDS:
            continue
        for name in POINTER.findall(hit['rest']):
            found[name] = kind if found.get(name, kind) == kind else None
    return {name: kind for name, kind in found.items() if kind and kind != 'void'}


def _block_start(clean, floor, at):
    """The offset of the brace that opens the innermost block holding `at`."""
    depth = 0
    for index in range(at - 1, floor - 1, -1):
        if clean[index] == '}':
            depth += 1
        elif clean[index] == '{':
            if not depth:
                return index
            depth -= 1
    return floor


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    head = clean.rfind(name, 0, part.opening)
    pointers = _pointers(clean[head + len(name):part.end])
    stores = [(pointers[s['base']], s['base'], s['field'], source[s.start('value'):s.end('value')])
              for s in STORE.finditer(clean, part.opening, part.end) if s['base'] in pointers]
    result, seen = [], set()
    for back in RETURN.finditer(clean, part.opening, part.end):
        target = back['name']
        kind = pointers.get(target)
        if not kind:
            continue
        here = clean[_block_start(clean, part.opening, back.start()):back.start()]
        for stored, base, field, value in stores:
            if stored != kind or base == target:
                continue
            if re.search(rf'\b{target}\s*->\s*{re.escape(field)}\s*=(?!=)', here):
                continue
            statement = f'{target}->{field} = {value};'
            before = clean[part.opening:back.start()].rstrip()
            if before[-1] in '{};:':
                indent = source[source.rfind('\n', 0, back.start()) + 1:back.start()]
                gap = '\n' + indent if not indent.strip() else ' '
                child = source[:back.start()] + statement + gap + source[back.start():]
            else:
                child = (source[:back.start()] + '{ ' + statement + ' ' + source[back.start():back.end()] + ' }'
                         + source[back.end():])
            if child not in seen:
                seen.add(child)
                result.append((FAMILY, child))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
