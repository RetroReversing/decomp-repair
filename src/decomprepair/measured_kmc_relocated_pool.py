"""Stage a relocated pool cursor and its index when the target uses both globals."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<index>{IDENT})\)\nlw \$v1, %lo\((?P=index)\)\(\$v1\)\n'
    rf'lui \$v0, %hi\((?P<table>{IDENT})\)\naddiu \$v0, \$v0, %lo\((?P=table)\)\n'
    r'sll \$v1, \$v1, 2\naddu \$v1, \$v1, \$v0\nlw \$v0, \(\$v1\)\n'
    r'addiu \$a0, \$v0, (?P<amount>\d+)\njr \$ra\nsw \$a0, \(\$v1\)'
)
_SOURCE = _shape('''
    s32 *@cursor;
    @cursor = (M2C_FIELD(&@base, s32 *, @index) * 4) + ((char *)&@base + @table);
    *@cursor += @amount;
''', numbers=('index', 'table', 'amount'))


def variants(source, name, header, rows, resolve=None):
    if not resolve or not 10 <= len(rows) <= 12:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not observed or not any(left.startswith('lui $v1, %hi(') and right.startswith('lui $v0, %hi(')
                               for left, right in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    sig = re.search(rf'\bvoid {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
    if (not draft or not sig or integer(draft['amount']) != int(observed['amount'])
            or re.search(r'\bvolatile\b|\b__repair_index\b', part.clean)):
        return []
    base = resolve(draft['base'])
    index, table = observed['index'], observed['table']
    if (base is None or base + integer(draft['index']) != resolve(index)
            or base + integer(draft['table']) != resolve(table) or index == table
            or re.search(rf'\b(?:{re.escape(index)}|{re.escape(table)})\b', part.clean + '\n' + _blank(header))):
        return []
    cursor = draft['cursor']
    body = (f'\n    s32 *{cursor};\n    s32 __repair_index;\n\n    {cursor} = &{table};\n'
            f'    __repair_index = {index};\n    {cursor} += __repair_index;\n'
            f'    *{cursor} += {draft["amount"]};\n')
    decl = f'extern s32 {index};\nextern s32 {table};\n\n'
    fixed = edit(source, [(sig.start(), sig.start(), decl), (part.opening + 1, part.end - 1, body)])
    return [('measured_relocated_pool_cursor', fixed)]
