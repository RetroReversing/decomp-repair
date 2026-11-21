"""Recover byte-strided lookups and a masked argument forwarded to a call."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_CALL = re.compile(
    rf'addiu \$sp, \$sp, -24\nsw \$s0, 16\(\$sp\)\nmove \$s0, \$a1\n'
    rf'sw \$ra, 20\(\$sp\)\njal (?P<call>{IDENT})\nandi \$a1, \$s0, 65535\n'
    r'sb \$s0, (?P<field>\d+)\(\$v0\)\nlw \$ra, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\n'
    r'jr \$ra\naddiu \$sp, \$sp, 24'
)
_LOAD = re.compile(
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\naddu \$at, \$at, \$v1\n'
    r'lw \$v1, %lo\((?P=table)\)\(\$at\)'
)
_BYTE = re.compile(
    rf'lui \$at, %hi\((?P<table>{IDENT})\)\naddu \$at, \$at, \$(?:s2|v0)\n'
    r'(?P<op>lbu|sb) \$v0, %lo\((?P=table)\)\(\$at\)'
)


def variants(source, name, header, rows):
    if not 10 <= len(rows) <= 65:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    if ((hit := _CALL.fullmatch(target)) and ('andi $a1, $s0, 65535', 'andi $a0, $a1, 65535') in changes):
        fixed = _call(part, name, header, hit)
        family = 'measured_masked_second_call_argument'
    elif ((byte := _BYTE.search(target)) and
          (f'{byte["op"]} $v0, %lo({byte["table"]})($at)',
           f'{"lw" if byte["op"] == "lbu" else "sw"} $v0, %lo({byte["table"]})($at)') in changes):
        fixed = _byte(part, byte, _LOAD.search(target), changes)
        family = 'measured_indexed_byte_global'
    else:
        return []
    return [(family, fixed)] if fixed else []


def _call(part, name, header, target):
    sig = re.search(rf'\bvoid {re.escape(name)}\(s32 ({IDENT}), (?P<type>s8) ({IDENT})\)\s*$', part.clean[:part.opening])
    body = re.fullmatch(
        rf'\s*M2C_FIELD\({target["call"]}\((?P<arg>{IDENT}) & 0xFFFF\), s8 \*, '
        rf'(?P<field>0[xX][0-9A-Fa-f]+|\d+)\) = (?P=arg);\s*', part.body)
    if (not sig or not body or sig[3] != body['arg'] or int(body['field'], 0) != int(target['field'])
            or re.search(rf'\b{re.escape(name)}\b', _blank(header) + part.clean[:sig.start()] + part.clean[part.end:])
            or not re.search(rf'\bvoid\s*\*{target["call"]}\(\);', part.clean[:part.opening])):
        return None
    start = part.opening + 1
    call = re.search(rf'\b{target["call"]}\(', part.body)
    return edit(part.source, [(*sig.span('type'), 's32'),
                             (start + call.end(), start + call.end(), f'{sig[1]}, ')])


def _byte(part, target, load, changes):
    byte, mode = target['table'], target['op']
    body = part.body
    args = []
    if mode == 'lbu':
        if not load or ('sll $v1, $v1, 2', 'sll $v1, $v1, 4') not in changes:
            return None
        pointer = load['table']
        pattern = re.compile(rf'\*\(&{pointer} \+ \(\((?P<index>{IDENT}) & 0xFFFF\) \* 0x64\)\)')
        hit = pattern.search(body)
        if not hit:
            return None
        args.append((hit.start(), hit.end(), f'*(void **)((char *)&{pointer} + (({hit["index"]} & 0xFFFF) * 0x64))'))
        byte_pattern = re.compile(rf'\*\(&{byte} \+ \(\((?P<index>{IDENT}) & 0xFFFF\) \* 0x64\)\)')
        found = byte_pattern.search(body)
        if not found or found['index'] != hit['index']:
            return None
        replacement = f'*(u8 *)((char *)&{byte} + (({found["index"]} & 0xFFFF) * 0x64))'
    else:
        if ('sll $s2, $v0, 2', 'sll $s2, $v0, 4') not in changes:
            return None
        addr = re.search(rf'(?P<tmp>{IDENT}) = (?P<offset>{IDENT}) \+ &(?P<base>{IDENT});', body)
        if not addr:
            return None
        args.append((addr.start(), addr.end(), f'{addr["tmp"]} = {addr["offset"]} + (u8 *)&{addr["base"]};'))
        found = re.search(rf'\*\(&{byte} \+ {addr["offset"]}\)', body)
        if not found:
            return None
        replacement = f'*(u8 *)((char *)&{byte} + {addr["offset"]})'
    args.append((found.start(), found.end(), replacement))
    start = part.opening + 1
    return edit(part.source, [(start + a, start + b, replacement) for a, b, replacement in args])
