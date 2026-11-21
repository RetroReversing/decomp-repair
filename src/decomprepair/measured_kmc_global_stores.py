"""Recover two stores through a repeatedly loaded relocated pointer."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<ptr>{IDENT})\)\nlw \$v1, %lo\((?P=ptr)\)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<first>{IDENT})\)\nlw \$v0, %lo\((?P=first)\)\(\$v0\)\n'
    r'sw \$v0, 4\(\$v1\)\n'
    r'lui \$v1, %hi\((?P=ptr)\)\nlw \$v1, %lo\((?P=ptr)\)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<second>{IDENT})\)\nlw \$v0, %lo\((?P=second)\)\(\$v0\)\n'
    r'sw \$v0, \(\$v1\)\njr \$ra\naddiu \$v0, \$zero, 1'
)
_SOURCE = _shape('''
    M2C_FIELD(M2C_FIELD(&@owner, void **, @pointer), s32 *, 4) = (s32) M2C_FIELD(&@data, s32 *, @first);
    M2C_FIELD(M2C_FIELD(&@owner, void **, @pointer), s32 *, 0) = (s32) M2C_FIELD(&@data, s32 *, @second);
    return 1;
''', numbers=('pointer', 'first', 'second'))


def variants(source, name, header, rows, resolve=None):
    if not resolve or len(rows) != 12:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not observed or (f'lui $v0, %hi({observed["second"]})', '') not in changes:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    sig = re.search(rf'\bs32 {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
    if not draft or not sig or re.search(r'\bvolatile\b', part.body):
        return []
    context = part.clean + '\n' + _blank(header)
    names = [observed[key] for key in ('ptr', 'first', 'second')]
    if len(set(names)) != 3 or any(re.search(rf'\b{re.escape(symbol)}\b', context) for symbol in names):
        return []
    addresses = [resolve(symbol) for symbol in names]
    if None in addresses or len(set(addresses)) != 3 or any(address % 4 for address in addresses):
        return []
    for symbol, base, offset in [(names[0], draft['owner'], draft['pointer']),
                                  (names[1], draft['data'], draft['first']),
                                  (names[2], draft['data'], draft['second'])]:
        address = resolve(base)
        if address is None or address + integer(offset) != resolve(symbol):
            return []
    pointer = f'M2C_FIELD(&{draft["owner"]}, void **, {draft["pointer"]})'
    first = f'M2C_FIELD(&{draft["data"]}, s32 *, {draft["first"]})'
    second = f'M2C_FIELD(&{draft["data"]}, s32 *, {draft["second"]})'
    body = source[part.opening + 1:part.end - 1]
    if body.count(pointer) != 2 or body.count(first) != 1 or body.count(second) != 1:
        return []
    body = body.replace(pointer, names[0]).replace(first, names[1]).replace(second, names[2])
    decl = f'extern void * volatile {names[0]};\nextern s32 {names[1]};\nextern s32 {names[2]};\n\n'
    fixed = edit(source, [(sig.start(), sig.start(), decl), (part.opening + 1, part.end - 1, body)])
    return [('measured_relocated_pointer_stores', fixed)]
