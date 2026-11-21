"""Recover a halfword switch state addressed by a byte stride."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'andi \$v1, \$a1, 65535\nsll \$v0, \$v1, 1\naddu \$v0, \$v0, \$v1\n'
    r'sll \$v0, \$v0, 3\naddu \$v0, \$v0, \$v1\nsll \$v0, \$v0, 2\n'
    rf'lui \$v1, %hi\((?P<table>{IDENT})\)\naddu \$v1, \$v1, \$v0\n'
    r'lhu \$v1, %lo\((?P=table)\)\(\$v1\)'
)
_STORE = re.compile(
    rf'addiu \$v0, \$zero, 1\nlui \$at, %hi\((?P<table>{IDENT})\)\n'
    rf'addu \$at, \$at, \$v1\nj {IDENT}\+\d+\nsh \$v0, %lo\((?P=table)\)\(\$at\)'
)


def variants(source, name, header, rows):
    if not 50 <= len(rows) <= 160:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    load, store = _TARGET.search(target), _STORE.search(target)
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (not load or not store or load['table'] != store['table']
            or ('sll $v0, $v0, 2', 'sll $v0, $v0, 4') not in changes
            or (f'sh $v0, %lo({load["table"]})($at)', f'sw $v0, %lo({load["table"]})($at)') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    table = load['table']
    if not re.search(rf'\bextern M2C_UNK {table}\s*;', part.clean[:part.opening] + header):
        return []
    expr = re.compile(
        rf'\*\(&{table} \+ \(\((?P<arg>{IDENT}) & 0xFFFF\) \* 0x64\)\)'
    )
    hits = list(expr.finditer(part.body))
    if len(hits) != 2 or hits[0]['arg'] != hits[1]['arg']:
        return []
    between = part.body[hits[0].end():hits[1].start()]
    if not re.search(r'^\s*;\s*switch\s*\([^{}]+\)\s*\{\s*case 0:', between):
        return []
    if not re.match(r'\s*=\s*1\s*;', part.body[hits[1].end():]):
        return []
    clean = part.clean[:part.opening]
    if not re.search(rf'\b{re.escape(name)}\([^{{;]*,\s*s32 {hits[0]["arg"]}\)\s*$', clean):
        return []
    edits = []
    for hit in hits:
        start = part.opening + 1 + hit.start()
        end = part.opening + 1 + hit.end()
        replacement = f'*(u16 *)((char *)&{table} + (({hit["arg"]} & 0xFFFF) * 0x64))'
        edits.append((start, end, replacement))
    return [('measured_halfword_switch_stride', edit(source, edits))]
