"""Retain a separately relocated record base in KMC GCC's address register."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'measured_global_rebase'
REG = r'\$\w+'
BYTE = r'(?:char|[su]8|(?:un)?signed\s+char)'
BASE_PAIR = re.compile(
    rf'lui (?P<reg>{REG}),\s*%hi\((?P<symbol>{IDENT})\)\n'
    rf'addiu (?P=reg),\s*(?P=reg),\s*%lo\((?P=symbol)\)\n'
    rf'lb[u]? {REG},\s*-(?P<offset>0x[0-9a-fA-F]+|[1-9][0-9]*)\((?P=reg)\)'
)
ASSIGN = re.compile(
    rf'(?<=[;{{}}])\s*(?P<dest>{IDENT})\s*=\s*'
    rf'(?P<rhs>\((?:s32|u32|int)\s*\*\)\s*\(\s*(?P<base>{IDENT})\s*\+\s*'
    r'(?P<offset>0x[0-9a-fA-F]+|[1-9][0-9]*)\s*\))\s*;'
)


def _carriers(before):
    """Locals definitely assigned before the rebase, with ordinary scalar reads."""
    declarations = re.compile(rf'(?<=[;{{}}])\s*(?:s32|u32|int)\s+({IDENT})\s*;')
    for decl in reversed(list(declarations.finditer(before))):
        name = decl[1]
        prefix = before[:decl.start()]
        if prefix.count('{') != prefix.count('}') + 1:
            continue
        initialized = re.match(rf'(?:\s*[^{{}};]+;)*?\s*{name}\s*=\s*[01]\s*;', before[decl.end():])
        if initialized:
            yield name


def _global(symbol, declarations, definition):
    return (re.search(rf'(?m)^\s*extern\s+{IDENT}\s+{symbol}\s*;', declarations)
            and not re.search(rf'(?m)^\s*#\s*define\s+{symbol}\b', declarations)
            and not re.search(rf'\b{IDENT}(?:\s+|\s*\*+\s*){symbol}\s*(?=[;,)=\[])', definition))


def variants(source, name, header, rows, *, resolve=None):
    """Use a measured relocation at a byte displacement from the draft's original anchor."""
    if resolve is None or not any('%hi(' in row[1] for row in rows):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:goto|asm|__asm__)\b', part.body):
        return []
    start, _ = find(source, name)
    definition = part.clean[start:part.end]
    globals_text = part.clean[:start] + '\n' + _blank(header)
    target = '\n'.join(' '.join(row[1].split()) for row in rows if row[1])
    result = []
    for evidence in BASE_PAIR.finditer(target):
        symbol = evidence['symbol']
        if not _global(symbol, globals_text, definition):
            continue
        address = resolve(symbol)
        if address is None:
            continue
        distance = int(evidence['offset'], 0)
        for hit in ASSIGN.finditer(part.clean, part.opening + 1, part.end):
            if int(hit['offset'], 0) != distance:
                continue
            before = part.clean[part.opening:hit.start()]
            if before.count('{') != before.count('}') + 1:
                continue
            base = hit['base']
            decl = re.search(rf'(?<=[;{{}}])\s*{BYTE}\s*\*\s*{base}\s*;', before)
            init = list(re.finditer(rf'(?<=[;{{}}])\s*{base}\s*=\s*&\s*({IDENT})\s*;', before))
            if not decl or len(init) != 1 or init[0].start() <= decl.start():
                continue
            after_init = before[init[0].end():]
            if (before[:init[0].start()].count('{') != before[:init[0].start()].count('}') + 1
                    or len(re.findall(rf'\b{base}\b', after_init))
                    != len(re.findall(rf'\(\s*\*\s*{base}\s*\)', after_init))):
                continue
            if not _global(init[0][1], globals_text, definition):
                continue
            original = resolve(init[0][1])
            if original is None or address - original != distance:
                continue
            for carrier in _carriers(before):
                # Unsigned cancellation preserves the address even if the scalar is negative.
                value = f'(s32 *)((((u32)&{symbol}) + {carrier}) - {carrier})'
                result.append((FAMILY, edit(source, [(*hit.span('rhs'), value)])))
                if len(result) == 4:
                    return result
    return result
