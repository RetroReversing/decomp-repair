"""Recover a contiguous byte buffer filled by a call after a signed clamp."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view

_CALL = re.compile(
    rf'jal (?P<getter>{IDENT})\nnop\nnor \$v1, \$zero, \$v0\n'
    r'sra \$v1, \$v1, (?:31|0x1[fF])\nand \$v0, \$v0, \$v1\n'
    rf'addiu \$a0, \$sp, (?P<slot>{NUMBER})\nlui \$a1, %hi\((?P<format>{IDENT})\)\n'
    rf'addiu \$a1, \$a1, %lo\((?P=format)\)\njal (?P<writer>{IDENT})\n'
    r'andi \$a2, \$v0, (?:65535|0x[fF]{4})\n'
)
_STACK = re.compile(rf'(?P<op>lbu|lb|lh|lhu|lw|sb|sh|sw) \$\w+, (?P<slot>{NUMBER})\(\$sp\)')


def target(lines):
    text = '\n'.join(' '.join(line.split()) for line in lines)
    if not (call := _CALL.search(text)):
        return None
    start = integer(call['slot'])
    if start % 4 or not 16 <= start <= 60:
        return None
    accesses = set()
    for match in _STACK.finditer(text):
        offset = integer(match['slot'])
        if start <= offset < start + 4:
            if match.start() <= call.end() - 1 or match['op'] != 'lbu':
                return None
            accesses.add(offset)
    return call if accesses == set(range(start, start + 3)) else None


def rewrite(source, name, header, call):
    local = '__repair_format_bytes'
    if local in source + header or not (part := view(source, name)):
        return None
    slot = integer(call['slot'])
    first, middle, last = (f'sp{offset:X}' for offset in range(slot, slot + 3))
    decl = re.search(rf'(?m)^[ \t]*u8 (?P<name>{first});[ \t]*$', part.body)
    invoke = re.search(
        rf'(?m)^(?P<pad>[ \t]*)(?P<value>{IDENT}) = {call["getter"]}\([^;\n]+\);[ \t]*\n'
        rf'(?P=pad)(?P<site>{call["writer"]}\(&{first}, &{call["format"]}, (?P=value) & \(\(s32\) ~(?P=value) >> (?:0x1[fF]|31)\) & (?:0x[fF]{{4}}|65535)\);)',
        part.body)
    if not decl or not invoke or decl.end() >= invoke.start():
        return None
    start = part.opening + 1
    before, after = part.body[:invoke.start('site')], part.body[invoke.end('site'):]
    slots = rf'\b(?:{first}|{middle}|{last})\b'
    if len(re.findall(slots, before)) != 1:
        return None
    occurrences = list(re.finditer(slots, after))
    if {item[0] for item in occurrences} != {first, middle, last}:
        return None
    # The bytes are read as characters or tested for zero. Other uses don't establish a buffer.
    if any(not re.match(r'\s*(?:-\s*(?:48|0x30)\b|!=\s*0\b)', after[item.end():]) for item in occurrences):
        return None
    base = start + invoke.end('site')
    value, pad = invoke['value'], invoke['pad']
    changes = [(start + decl.start('name'), start + decl.end('name'), f'{local}[4]'),
               (start + invoke.start('site'), base,
                f'{value} &= (s32)~{value} >> 31;\n{pad}{call["writer"]}({local}, &{call["format"]}, {value} & 0xFFFF);')]
    changes.extend((base + item.start(), base + item.end(), f'{local}[{int(item[0][2:], 16) - slot}]')
                   for item in occurrences)
    return edit(source, changes)
