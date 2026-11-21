"""Recover an event record when separately guessed stack locals lose two bytes."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'addiu \$sp, \$sp, -40\naddiu \$v0, \$zero, (?P<code>\d+)\n'
    r'addiu \$a0, \$a0, (?P<queue>\d+)\nsb \$a1, 20\(\$sp\)\n'
    r'addiu \$a1, \$sp, 16\nsb \$a2, 21\(\$sp\)\nmove \$a2, \$zero\n'
    rf'sw \$ra, 32\(\$sp\)\njal (?P<post>{IDENT})\nsh \$v0, 16\(\$sp\)\n'
    r'lw \$ra, 32\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 40'
)
_SOURCE = _shape('''
    s16 @event; s8 @first; s8 @second;
    @first = @argone; @second = @argtwo; @event = @code;
    @post(@queue + @offset, &@event, 0);
''', numbers=('code', 'offset'))


def variants(source, name, header, rows):
    if len(rows) != 13:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    hit = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (not hit or ('sb $a1, 20($sp)', '') not in changes
            or ('sb $a2, 21($sp)', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if (not draft or draft['post'] != hit['post'] or integer(draft['code']) != int(hit['code'])
            or integer(draft['offset']) != int(hit['queue']) or re.search(r'\b__repair_event\b', part.clean)):
        return []
    sig = re.search(rf'\bvoid {re.escape(name)}\(s32 ({IDENT}), s8 ({IDENT}), s8 ({IDENT})\)\s*$',
                    part.clean[:part.opening])
    if not sig or sig.groups() != (draft['queue'], draft['argone'], draft['argtwo']):
        return []
    body = (f'\n    struct {{ s16 code; s16 pad; s8 first; s8 second; s8 tail[4]; }} __repair_event;\n\n'
            f'    __repair_event.first = {draft["argone"]};\n'
            f'    __repair_event.second = {draft["argtwo"]};\n'
            f'    __repair_event.code = {draft["code"]};\n'
            f'    {draft["post"]}({draft["queue"]} + {draft["offset"]}, &__repair_event.code, 0);\n')
    fixed = edit(source, [(part.opening + 1, part.end - 1, body)])
    return [('measured_stack_event_record', fixed)]
