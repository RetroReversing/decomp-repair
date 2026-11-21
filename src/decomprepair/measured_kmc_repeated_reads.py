"""Recover repeated global reads visible in KMC target code."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_POLL_TARGET = re.compile(
    rf'lui \$v1, %hi\((?P<global>{IDENT})\)\nlw \$v1, %lo\((?P=global)\)\(\$v1\)\n'
    r'addiu \$v0, \$zero, 1\nbne \$v1, \$v0, 40\nnop\naddiu \$v1, \$zero, 1\n'
    r'lui \$v0, %hi\((?P=global)\)\nlw \$v0, %lo\((?P=global)\)\(\$v0\)\n'
    r'beq \$v0, \$v1, 24\nnop\njr \$ra\nnop'
)
_POLL_SOURCE = _shape('if (@global == 1) { do { } while (@global == 1); }')
_XOR_TARGET = re.compile(
    rf'beqz \$a0, 28\nnop\nlui \$v0, %hi\((?P<global>{IDENT})\)\n'
    r'addiu \$v0, \$v0, %lo\((?P=global)\)\nlw \$v0, \(\$v0\)\n'
    rf'j (?P<name>{IDENT})\+40\nxor \$v0, \$v0, \$a0\n'
    r'lui \$v0, %hi\((?P=global)\)\naddiu \$v0, \$v0, %lo\((?P=global)\)\n'
    r'lw \$v0, \(\$v0\)\njr \$ra\nsltu \$v0, \$zero, \$v0'
)
_XOR_SOURCE = _shape('''
    s32 @value;
    if (@arg != 0) { @value = M2C_FIELD(&@base, s32 *, @offset) ^ @arg; }
    else { @value = M2C_FIELD(&@base, s32 *, @offset); }
    return @value != 0;
''', numbers=('offset',))


def variants(source, name, header, rows, resolve=None):
    if len(rows) != 12:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = ' '.join(part.body.split())
    poll = _POLL_TARGET.fullmatch(target)
    xor = _XOR_TARGET.fullmatch(target)
    if poll and (f'lui $v0, %hi({poll["global"]})', '') in changes:
        draft = _POLL_SOURCE.fullmatch(body)
        declaration = re.search(rf'\bextern (?P<type>s32) {poll["global"]}\s*;', part.clean[:part.opening])
        if (not draft or draft['global'] != poll['global'] or not declaration
                or re.search(rf'\b{poll["global"]}\b', _blank(header))
                or not re.search(rf'\bvoid {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])):
            return []
        fixed = edit(source, [(*declaration.span('type'), 'volatile s32'),
                              (part.opening + 1, part.end - 1, f'\n    while ({draft["global"]} == 1) {{}}\n')])
        return [('measured_volatile_global_poll', fixed)]
    if xor and xor['name'] == name and resolve:
        draft = _XOR_SOURCE.fullmatch(body)
        signature = re.search(rf'\bs32 {re.escape(name)}\(s32 ({IDENT})\)\s*$', part.clean[:part.opening])
        if (not draft or not signature or signature[1] != draft['arg']
                or ('addiu $v0, $v0, %lo(' + xor['global'] + ')', '') not in changes):
            return []
        base = resolve(draft['base'])
        if base is None or base + integer(draft['offset']) != resolve(xor['global']):
            return []
        symbol = xor['global']
        context = part.clean + _blank(header)
        if re.search(rf'\b{symbol}\b', context):
            return []
        expression = f'M2C_FIELD(&{draft["base"]}, s32 *, {draft["offset"]})'
        body_source = source[part.opening + 1:part.end - 1]
        if body_source.count(expression) != 2:
            return []
        replacement = body_source.replace(expression, f'*(volatile s32 *)&{symbol}')
        fixed = edit(source, [(signature.start(), signature.start(), f'extern s32 {symbol};\n\n'),
                              (part.opening + 1, part.end - 1, replacement)])
        return [('measured_volatile_global_branch_read', fixed)]
    return []
