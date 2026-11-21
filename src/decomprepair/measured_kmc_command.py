"""Stage a command word when an unprototyped allocator was given a stale argument."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'jal (?P<alloc>{IDENT})\nmove \$s1, \$v0\nmove \$s2, \$v0\n'
    rf'jal (?P<init>{IDENT})\nmove \$a0, \$s2\nlw \$v1, (?P<field>\d+)\(\$s1\)\n'
    r'lui \$a0, (?P<hi>\d+)\nori \$a0, \$a0, (?P<lo>\d+)\n'
    r'addiu \$v0, \$v1, 8\nsw \$v0, (?P=field)\(\$s1\)\nsw \$a0, \(\$v1\)\n'
    r'jal (?P=alloc)\nsw \$s2, 4\(\$v1\)'
)
_SOURCE = re.compile(
    rf'(?P<context>{IDENT}) = (?P<get>{IDENT})\(\);\s*(?P<value>{IDENT}) = (?P<alloc>{IDENT})\(\);\s*'
    rf'(?P<init>{IDENT})\((?P=value)\);\s*(?P<cursor>{IDENT}) = M2C_FIELD\((?P=context), void \*\*, (?P<field>{NUMBER})\);\s*'
    rf'M2C_FIELD\((?P=context), void \*\*, (?P=field)\) = \(void \*\) \((?P=cursor) \+ 8\);\s*'
    rf'(?P<store>M2C_FIELD\((?P=cursor), s32 \*, 0\) = (?P<word>{NUMBER});)\s*'
    rf'M2C_FIELD\((?P=cursor), s32 \*, 4\) = (?P=value);\s*'
    rf'(?P=value) = (?P=alloc)\((?P=word)\);'
)


def variants(source, name, header, rows):
    if not 40 <= len(rows) <= 90:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.search(target)
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (not hit or len(changes) != 3 or ('sw $a0, ($v1)', 'sw $a1, ($v1)') not in changes
            or ('', f'lui $a1, {hit["hi"]}') not in changes
            or ('', f'ori $a1, $a1, {hit["lo"]}') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.search(part.body)
    temporary = '__repair_command_word'
    if (not draft or temporary in part.clean + _blank(header)
            or draft['alloc'] != hit['alloc'] or draft['init'] != hit['init']
            or integer(draft['field']) != int(hit['field'])
            or integer(draft['word']) != (int(hit['hi']) << 16 | int(hit['lo']))):
        return []
    allocator = draft['alloc']
    if not re.search(rf'\bs32 {allocator}\(\);', part.clean[:part.opening]):
        return []
    local = re.search(rf'\bs32\s+(?P<value>{draft["value"]})\s*;', part.body)
    if not local:
        return []
    start = part.opening + 1
    store = draft['store']
    replacement = f'{temporary} = {draft["word"]};\n    ' + store.replace(draft['word'], temporary)
    call = f'{allocator}({draft["word"]})'
    position = part.body.find(call, draft.start(), draft.end())
    if position < 0:
        return []
    fixed = edit(source, [
        (start + local.start(), start + local.end(), f'u32 {draft["value"]};\n    s32 {temporary};'),
        (start + draft.start('store'), start + draft.end('store'), replacement),
        (start + position, start + position + len(call), f'{allocator}()'),
    ])
    return [('measured_staged_command_word', fixed)]
